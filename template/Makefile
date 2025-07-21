{% if data.platform=='dig' %}
default:sim_dig
{% elif data.platform=='vams' %}
default: sim_vams
{% endif %}


LD_LIBRARY_PATH = /tools/synopsys/verdi/Verdi_0-2018.09-SP2/share/PLI/IUS/Linux64
UVM_HOME = /tools/cadence/XCELIUM2103_s006/tools.lnx86/methodology/UVM/CDNS-1.2/sv
UVM_VERBOSITY = UVM_LOW
TESTNAME = {{ data.pattern }}

FSDB := 1
GUI := 0
FLAGS :=
SEED := $(shell date +%s)

ifeq (${FSDB},1)
    FLAGS := ${FLAGS} +FSDB_DUMP -SVSEED=${SEED}
endif

ifeq (${GUI},1)
    FLAGS := ${FLAGS} -gui
endif

testcase = $(shell if [-f test.sv  ];then echo "test.sv exist";fi)
ctrl_tcl = $(shell if [-f ctrl.tcl ];then echo "ctrl.tcl exist";fi)
load_tcl = $(shell if [-f load_tcl ];then echo "load_tcl exist";fi)

pre:
    $(if $(testcase),, ln -sf ../../tc/{{ data.pattern }}/{{ data.pattern }}.sv .test.sv)
    cp -rf ../../tc/{{ data.pattern }}/signal.rc ./out/

sim_dig:pre
    -cp xrun.log xrun.log_history
    rm cds.lib hdl.var -f
    xrun -64 \ 
		{FLAGS} \
        -uvm +UVM_VERBOSITY=$(UVM_VERBOSITY) -uvmnocdnsextra -quiet -incdir $(UVM_HOME)/src \
        -UVM_TESTNAME={{ data.pattern }} \
        -top tb -sv -v93 -f xrun_sv_args \
        -f ../../rtl/vlog.f \
        -timescale 1ns/1ns \
        -xmlibdirpath out \
        -access +rwc \
        -ierreport


wave:
    verdi -uvm -f ../../rtl/vlog.f -f xrun_sv_args  -autoalias -nologo -sv -top tb -ssf out/sim.fsdb &

error:
    egrep "ERROR|Error[SEED]|*E" xrun.log

clean:
    -rm -rf *.o lib.a *.log xcelium.d *raw *shm *history spectre* out/*