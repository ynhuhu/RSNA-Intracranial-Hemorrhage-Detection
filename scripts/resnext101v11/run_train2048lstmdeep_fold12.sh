N_GPU=1
WDIR='resnext101v11'
FOLD=0
SIZE='384'

for FOLD in  0 1 2    # 0 1 2 3 4 5 6 7 8
do
    for GEPOCH in 0 1 2 3 4
    do
        bsub  -q lowpriority -gpu "num=$N_GPU:mode=exclusive_process" -app gpu -n =$N_GPU  -env LSB_CONTAINER_IMAGE=darraghdog/kaggle:apex_build \
            -m dbslp1830 -n 1 -R "span[ptile=4]" -o log_train_%J  sh -c "cd /share/dhanley2/rsna/scripts/$WDIR  && python3 trainlstmdeep.py  \
            --logmsg Rsna-lb-$SIZE-fp16 --epochs 9 --fold $FOLD  --lr 0.0001 --batchsize 4  --workpath scripts/$WDIR  \
            --nbags 8 --globalepoch $GEPOCH  --loadcsv F --lstm_units 2048 --dropout 0.3 --size $SIZE"
    done
done
