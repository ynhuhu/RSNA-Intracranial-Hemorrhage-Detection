N_GPU=1
WDIR='resnext101v6'
FOLD=0
SIZE='384'

for GEPOCH in 1 # 2 3 4 5 6
do
    for FOLD in 0 1 2
    do
        bsub  -q lowpriority -gpu "num=$N_GPU:mode=exclusive_process" -app gpu -n =$N_GPU  -env LSB_CONTAINER_IMAGE=darraghdog/kaggle:apex_build \
            -n 1 -R "span[ptile=4]" -o log_train_%J  sh -c "cd /share/dhanley2/rsna/scripts/$WDIR  && python3 trainlstmdeep.py  \
            --logmsg Rsna-lb-$SIZE-fp16 --epochs 6 --fold $FOLD  --lr 0.0001 --batchsize 4  --workpath scripts/$WDIR  \
            --nbags 4 --globalepoch $GEPOCH  --loadcsv F --lstm_units 1024 --dropout 0.3 --size $SIZE"
    done
done
