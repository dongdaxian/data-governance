# data-governance

记得在.gitignore同级目录建一个.env文件，然后写入
API_KEY=xxxxxx
MILVUS_URI=xxxxxx
MILVUS_TOKEN=xxxxxx


1. 不考虑到数据示例包含说明性文字的情况，默认为真实数据。
2. 不需要考虑权威系统相关逻辑，因为无论如何都要治理人员和权威系统沟通后才有结果，因此所有标准统一按非权威系统来处理。