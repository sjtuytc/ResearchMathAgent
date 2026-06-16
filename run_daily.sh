#!/bin/bash
# Daily autonomous cycle: solve + discover issues + resolve them
# Run from cron: 0 9 * * * /projects/bhov/zzhao18/code/ResearchMathAgent-web/run_daily.sh
cd /projects/bhov/zzhao18/code/ResearchMathAgent-web
/sw/user/python/miniforge3-pytorch-2.11.0/bin/python3.12 -m webapp.daily --once >> /tmp/rma_daily.log 2>&1
