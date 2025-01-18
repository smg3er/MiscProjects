# Первые числа 0 и 1 а каждое следующее это сумма предыдущих
# 0 1 2 3 5 8 13 21
import time
n = int(input('Введите кол-во итераций расчета Фибоначчи: '))
time_start = time.time()
print('start processing in range: ', n)
fibo = [0, 1]
for i in range(0, n):
    if i>=2:
        fibo.append(fibo[i-2]+fibo[i-1])
time_end = time.time()
print(time_end-time_start)
