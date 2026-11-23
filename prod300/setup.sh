#!/bin/bash
# setup.sh [--submit] [P]: newcase.sh for every case in cases.txt, P at a time. Results in state/setup.tsv.
D=/lus/flare/projects/FRAME-IDP/fkunnath/ma/prod300; MODE=${1:-}; P=${2:-16}
mkdir -p $D/logs/setup $D/state; : > $D/state/setup${MODE:+-submit}.tsv
one() { t0=$(date +%s); if $D/newcase.sh "$1" $MODE > $D/logs/setup/$1${MODE:+-submit}.log 2>&1; then r=ok; else r=FAIL; fi
        echo -e "$1\t$r\t$(( $(date +%s) - t0 ))" >> $D/state/setup${MODE:+-submit}.tsv; }
export -f one; export D MODE
xargs -P "$P" -I{} bash -c 'one {}' < $D/cases.txt
echo "$(cut -f2 $D/state/setup${MODE:+-submit}.tsv | sort | uniq -c | tr '\n' ' ')"
