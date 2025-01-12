import time
import mmh3
import hashlib
import uuid
import matplotlib.pyplot as plt

def func_sha1(string):
    hash_1 = int.from_bytes(hashlib.sha1(string.encode('utf-8')).digest(), 'big')
    return hash_1

def func_sha256(string):
    hash_256 = int.from_bytes(hashlib.sha256(string.encode('utf-8')).digest(), 'big')
    return hash_256

def func_mmh3(string):
    return mmh3.hash(string, signed=False)

nodes_list = [
    '192.168.68.109_r0',
    '192.168.68.107_r0',
    '192.168.68.106_r0',
    '192.168.68.105_r0'
]

start=time.time()
print('Process started...')

nodes_list_hash = []
for i in nodes_list:
    nodes_list_hash.append(func_sha1(i))

request_distributions = {}
for j in nodes_list:
    request_distributions[j]=0

req_qty = 10_000
for k in range (req_qty):
    key = str(uuid.uuid4())
    hash_key = func_sha1(key)
    tmp_nodes_keys_abs=[]
    for n in nodes_list_hash:
        tmp_nodes_keys_abs.append(abs((n-hash_key)))
    request_node_index = tmp_nodes_keys_abs.index(min(tmp_nodes_keys_abs))
    node = nodes_list[request_node_index]
    request_distributions[node]+=1
    print ('Found new request ', key, '>>>>>', 'to node: ', node)

end=time.time()

print('Total processing time is: ', end-start)

plt.bar(list(request_distributions.keys()), list(request_distributions.values()))
plt.show()

##Видим, что результат распределен всеже неравномерно.
##TODO
##Проработать функцию хеширования