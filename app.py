from flask import Flask, render_template, request, jsonify
from jinja2 import Environment, FileSystemLoader
import os
import csv
import subprocess
import time
import re
import getpass
import fcntl
import shutil
import logging

app = Flask(__name__)

# 配置日志
#logging.basicConfig(level=logging.INFO)
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('regression.log'),   # 可选：输出到文件
        logging.StreamHandler()                  # 控制台只打印 WARNING 及以上
    ]
)

logging.getLogger('werkzeug').setLevel(logging.ERROR)  # 关闭 Werkzeug 访问日志

logger = logging.getLogger(__name__)

# User define
username = getpass.getuser()
template_dir = './template'
tmp_path = f"/scratch/XL007_VS/{username}/workarea_1p0/"
bsub_cmd = 'bsub -m titan06 make'

def find_string(file_list):
    fd = 0
    for line in file_list:
        line = line.strip().lower()
        if "sim pass" in line:
            fd = 1
            logger.info(f"Found SIM PASS in log: {line}")
        elif "sim fail" in line:
            fd = 0
            logger.info(f"Found SIM FAIL in log: {line}")
        elif "sim timout" in line:
            fd = 2
            logger.info(f"Found SIM TIMEOUT in log: {line}")
        elif "sim timeout" in line:
            fd = 2
            logger.info(f"Found SIM TIMEOUT in log: {line}")
    return fd

def tail_file(file_path):
    if not os.path.isfile(file_path):
        logger.warning(f"File not found: {file_path}")
        return None
    try:
        size = os.path.getsize(file_path)
        if size == 0:
            return None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(file_path, 'r', errors='ignore') as f:
                    fl = f.fileno()
                    fcntl.fcntl(fl, fcntl.F_SETFL, os.O_NONBLOCK)
                    time.sleep(0.1)
                    if size > 1024:
                        f.seek(max(0, size - 1024))
                        content = f.read()
                    else:
                        content = f.read()
                    lines = content.splitlines()
                    if not lines:
                        return None
                    last_line = next((line.strip() for line in reversed(lines) if line.strip()), None)
                    return last_line[:80] if last_line else None
            except (IOError, OSError) as e:
                logger.warning(f"Retry {attempt + 1} for {file_path}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.5)
                continue
        return None
    except Exception as e:
        logger.error(f"Error reading tail of {file_path}: {e}")
        return None

def check_pid_in_bjobs_output(bjobs_output, pid):
    return str(pid) in bjobs_output

def extract_bjobs_id(output):
    match = re.search(r'Job <(\d+)>', output.decode('utf-8', errors='ignore'))
    return match.group(1) if match else None

def remove_comments(content):
    lines = content.split('\n')
    filtered_lines = [line for line in lines if not line.strip().startswith('#')]
    return '\n'.join(filtered_lines)

def parse_csv(csv_file):
    testcases = []
    try:
        logger.info(f"Parsing CSV file: {csv_file}")
        with open(csv_file, 'r') as file:
            content = file.read().replace(' ', '')
            content = remove_comments(content)
            reader = csv.DictReader(content.splitlines())
            if not reader.fieldnames:
                logger.error("CSV file has no header row")
                return []
            variable_names = reader.fieldnames
            for row in reader:
                a = [str(row[name]).strip() for name in variable_names]
                b = "_".join(a)
                testcases.append({
                    'config': row,
                    'name': b,
                    'dir': None,
                    'pid': None,
                    'status': 'Pending',
                    'log': '',
                    'result': None
                })
        logger.info(f"Parsed {len(testcases)} testcases")
        return testcases
    except Exception as e:
        logger.error(f"Error parsing CSV: {e}")
        return []

def create_testcase_directory(config, variable_names):
    env = Environment(loader=FileSystemLoader(template_dir))
    variables = {name: config[name] for name in variable_names}
    a = [str(variables[name]).strip() for name in variable_names]
    b = "_".join(a)
    output_dir = os.path.join('./', b)
    link_path = os.path.join(tmp_path, b)
    link_source = os.path.join(output_dir, 'out')
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        if not os.path.exists(link_path):
            os.makedirs(link_path, exist_ok=True)
        if not os.path.exists(link_source):
            os.symlink(link_path, link_source)
        for root, dirs, files in os.walk(template_dir):
            for file in files:
                relative_path = os.path.relpath(os.path.join(root, file), template_dir)
                template = env.get_template(relative_path)
                rendered_content = template.render(data=variables)
                output_file = os.path.join(output_dir, relative_path)
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, 'w') as f:
                    f.write(rendered_content)
        return output_dir
    except (OSError, FileExistsError) as e:
        logger.error(f"Error creating directory for {output_dir}: {e}")
        return None

def delete_case_directory(dir_path):
    try:
        shutil.rmtree(dir_path)
        for tc in testcases:
            if tc['dir'] == dir_path:
                tc['dir'] = None
                tc['pid'] = None
                tc['status'] = 'Pending'
                tc['log'] = ''
                tc['result'] = None
        return True
    except Exception as e:
        logger.error(f"Failed to delete directory {dir_path}: {e}")
        return False

testcases = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/load_testcases', methods=['POST'])
def load_testcases():
    global testcases
    if 'csv_file' not in request.files:
        logger.error("No CSV file provided in request")
        return jsonify({'error': 'No CSV file provided'}), 400
    csv_file = request.files['csv_file']
    if csv_file.filename == '':
        logger.error("No file selected")
        return jsonify({'error': 'No selected file'}), 400
    csv_path = os.path.join('./', csv_file.filename)
    csv_file.save(csv_path)
    testcases = parse_csv(csv_path)
    return jsonify({'testcases': testcases})

@app.route('/create_testcase', methods=['POST'])
def create_testcase():
    global testcases
    index = int(request.json.get('index'))
    if 0 <= index < len(testcases) and not testcases[index]['dir']:
        config = testcases[index]['config']
        variable_names = list(config.keys())
        dir_path = create_testcase_directory(config, variable_names)
        if dir_path:
            testcases[index]['dir'] = dir_path
            testcases[index]['status'] = 'Created'
            return jsonify({'status': 'created', 'dir': dir_path})
    return jsonify({'error': 'Failed to create testcase'}), 500

@app.route('/run_testcase', methods=['POST'])
def run_testcase():
    global testcases
    index = int(request.json.get('index'))
    if 0 <= index < len(testcases) and testcases[index]['dir'] and not testcases[index]['pid']:
        dir_path = testcases[index]['dir']
        if not os.path.isfile(os.path.join(dir_path, 'Makefile')):
            return jsonify({'error': 'Makefile not found'}), 400
        try:
            process = subprocess.Popen(
                bsub_cmd,
                cwd=dir_path,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = process.communicate(timeout=10)  # 增加超时等待
            logger.info(f"bsub stdout: {stdout.decode('utf-8', errors='ignore')}")
            logger.info(f"bsub stderr: {stderr.decode('utf-8', errors='ignore')}")
            if process.returncode == 0:
                bjobs_id = extract_bjobs_id(stdout)
                if bjobs_id:
                    testcases[index]['pid'] = bjobs_id
                    testcases[index]['status'] = 'Running'
                    return jsonify({'status': 'started', 'pid': bjobs_id})
                else:
                    logger.error(f"No job ID extracted from stdout: {stdout}")
            else:
                logger.error(f"bsub failed with return code {process.returncode}: {stderr}")
        except subprocess.TimeoutExpired:
            logger.warning(f"bsub command timed out for {dir_path}")
        except Exception as e:
            logger.error(f"Error running testcase in {dir_path}: {e}")
    return jsonify({'error': 'Failed to start job'}), 500

@app.route('/run_selected', methods=['POST'])
def run_selected():
    global testcases
    selected = request.json.get('selected', [])
    for index in selected:
        index = int(index)
        if 0 <= index < len(testcases) and testcases[index]['dir'] and not testcases[index]['pid']:
            dir_path = testcases[index]['dir']
            if not os.path.isfile(os.path.join(dir_path, 'Makefile')):
                continue
            try:
                process = subprocess.Popen(
                    bsub_cmd,
                    cwd=dir_path,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, stderr = process.communicate(timeout=10)
                logger.info(f"bsub stdout for {dir_path}: {stdout.decode('utf-8', errors='ignore')}")
                if process.returncode == 0:
                    bjobs_id = extract_bjobs_id(stdout)
                    if bjobs_id:
                        testcases[index]['pid'] = bjobs_id
                        testcases[index]['status'] = 'Running'
                    else:
                        logger.error(f"No job ID extracted for {dir_path}: {stdout}")
                else:
                    logger.error(f"bsub failed for {dir_path} with return code {process.returncode}: {stderr}")
            except subprocess.TimeoutExpired:
                logger.warning(f"bsub command timed out for {dir_path}")
            except Exception as e:
                logger.error(f"Error running testcase in {dir_path}: {e}")
    return jsonify({'status': 'started'})

@app.route('/delete_testcase', methods=['POST'])
def delete_testcase():
    index = int(request.json.get('index'))
    if 0 <= index < len(testcases) and testcases[index]['dir']:
        dir_path = testcases[index]['dir']
        if delete_case_directory(dir_path):
            return jsonify({'status': 'deleted'})
    return jsonify({'error': 'Failed to delete testcase'}), 500

@app.route('/create_selected', methods=['POST'])
def create_selected():
    global testcases
    selected = request.json.get('selected', [])
    for index in selected:
        index = int(index)
        if 0 <= index < len(testcases) and not testcases[index]['dir']:
            config = testcases[index]['config']
            variable_names = list(config.keys())
            dir_path = create_testcase_directory(config, variable_names)
            if dir_path:
                testcases[index]['dir'] = dir_path
                testcases[index]['status'] = 'Created'
    return jsonify({'status': 'created'})

@app.route('/delete_selected', methods=['POST'])
def delete_selected():
    global testcases
    selected = request.json.get('selected', [])
    for index in selected:
        index = int(index)
        if 0 <= index < len(testcases) and testcases[index]['dir']:
            dir_path = testcases[index]['dir']
            delete_case_directory(dir_path)
    return jsonify({'status': 'deleted'})

@app.route('/get_status', methods=['GET'])
def get_status():
    global testcases
    status = {'cases': [], 'summary': {'pass': 0, 'fail': 0, 'timeout': 0}}
    all_finished = True
    try:
        process = subprocess.Popen(['bjobs', '-a'], shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, stderr = process.communicate()
        if process.returncode == 0:
            bjobs_output = output.decode('utf-8', errors='ignore')
            logger.info(f"bjobs -a output: {bjobs_output}")
            for tc in testcases:
                if tc['pid']:
                    if check_pid_in_bjobs_output(bjobs_output, tc['pid']):
                        log_file = os.path.join(tc['dir'], 'xrun.log')
                        tc['log'] = tail_file(log_file) if tc['log'] != 'Finished' else tc['log']
                        tc['status'] = 'Running'
                        all_finished = False
                        logger.info(f"Running: {tc['name']} (PID: {tc['pid']})")
                    else:
                        log_file = os.path.join(tc['dir'], 'xrun.log')
                        if os.path.isfile(log_file):
                            logger.info(f"Processing finished log: {log_file}")
                            with open(log_file, 'r') as f:
                                lines = f.readlines()
                                result = find_string(lines)
                                logger.info(f"find_string result for {tc['name']}: {result}")
                                tc['result'] = 'PASS' if result == 1 else 'TIMEOUT' if result == 2 else 'FAIL'
                                tc['status'] = 'Finished'
                                tc['log'] = f"Result: {tc['result']}"
                                if result == 1:
                                    status['summary']['pass'] += 1
                                elif result == 2:
                                    status['summary']['timeout'] += 1
                                else:
                                    status['summary']['fail'] += 1
                                tc['pid'] = None
                                logger.info(f"Finished: {tc['name']} (Result: {tc['result']})")
                status['cases'].append({
                    'config': tc['config'],
                    'name': tc['name'],
                    'pid': tc['pid'],
                    'dir': tc['dir'],
                    'status': tc['status'],
                    'log': tc['log'] if tc['log'] else 'No log yet',
                    'result': tc['result']
                })
    except Exception as e:
        logger.error(f"Error getting status: {e}")
    if all_finished:
        status['summary']['total'] = len(testcases)
        logger.info(f"All finished, total cases: {status['summary']['total']}")
    return jsonify(status)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)