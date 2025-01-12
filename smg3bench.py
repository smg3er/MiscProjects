import random
import time
rand_list=[]
print('Start processing...')
start = time.time()
while len(rand_list)<10_000_000:
    a = random.randint(0,999999999999999999)
    ##print (a)
    rand_list.append(a)
rand_list.sort()
print('The length of rand_list is: {r}'.format(r=len(rand_list)))
end = time.time()
print('Execution time sec: ', end-start)

