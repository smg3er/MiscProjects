import time
import sys
from locale import format

sys.set_int_max_str_digits(0)
start = time.time()

digit_dict={}
digit = int(input('Введите число: '))
for i in range(0, digit+1):
    digit_dict[i] = 1
    for j in range(1, i+1):
        digit_dict[i] = digit_dict[i]*j
    print('Factorio ', i, '! = ', digit_dict[i])
end = time.time()
print('Execution time is: ', end-start, ' sec.')
