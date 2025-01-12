import hashlib

def calculate_md5(file_path):
    with open(file_path, 'rb') as file:
        md5_hash = hashlib.md5()
        while True:
            chunk = file.read(4096)
            if not chunk:
                break
            md5_hash.update(chunk)
    return md5_hash.hexdigest()
def verify_md5(file_path, expected_md5):
    calculated_md5 = calculate_md5(file_path)
    if calculated_md5 == expected_md5:
        print()
        print(f'Файл "{file_path}" корректен')
        print(f'Рассчитанный хэш "{calculated_md5}"')
        print(f'Ожидаемый хэш"{expected_md5}"')
    else:
        print()
        print(f'Файл "{file_path}" не корректен!!!!!!!')
        print(f'Рассчитанный хэш "{calculated_md5}"')
        print(f'Ожидаемый хэш "{expected_md5}"')

file_path = 'C:\Downloads\Anaconda3-2021.11-Windows-x86_64.exe'
expected_md5 = '16933b56706a240e2c9a00983ed00cbb'

verify_md5(file_path, expected_md5)