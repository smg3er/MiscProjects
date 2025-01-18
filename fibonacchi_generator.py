# Первые числа 0 и 1 а каждое следующее это сумма предыдущих
# 0 1 2 3 5 8 13 21
import time
import sys
sys.set_int_max_str_digits(100000)
n = int(input('Введите кол-во итераций расчета Фибоначчи: '))
time_start = time.time()
a = 0
b = 1
for i in range(n):
    a, b = b, a+b
    with open('C:\\Users\\smg3e\\OneDrive\\Рабочий стол\\fibo.txt', 'a') as file:
        file.write(str(a) + ',' +  '\n')
time_end = time.time()
print(time_end-time_start)
