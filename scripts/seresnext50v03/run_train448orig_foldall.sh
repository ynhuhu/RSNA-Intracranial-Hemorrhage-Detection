N_GPU=1
WDIR='seresnext50v03'
FOLD=0
SIZE='448'

for FOLD in 1 # 2 3
do
    bsub  -q lowpriority -gpu "num=$N_GPU:mode=exclusive_process" -app gpu -n =$N_GPU  -env LSB_CONTAINER_IMAGE=darraghdog/kaggle:rsna \
            -m dbslp1897  -n 1 -R "span[ptile=4]" -o log_train_%J  sh -c "cd /share/dhanley2/rsna/scripts/$WDIR  && python3 trainorig.py  \
            --start 5 --logmsg Rsna-lb-$SIZE-fp16 --epochs 7 --fold $FOLD  --lr 0.00002 --batchsize 48  --workpath scripts/$WDIR  \
            --imgpath data/mount/512X512X6/ --size $SIZE --weightsname weights/model_512_resnext101$FOLD.bin"
done
