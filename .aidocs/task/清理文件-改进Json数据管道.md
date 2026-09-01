# 清理文件-改进Json数据管道

1. 目前不需要用到 run_v1_spider 和 run_v2_spider 两个文件，请为我安全地移除这两个文件，确保它们不会影响到使用 scrapy 开发的程序代码。

2. 移除该项目对线性模式的支持，目前已经非常确定，线性模式只能获取到有限的一万条数据，所以不需要改模式。 

## Json 数据持久化处理管道

关于 json 文件的命名，它可以使用 query_hash 联合 cur_page (这个是 crawl_query_state 表中的字段，反映当前正在处理的桶内的页数) 进行命名, 这样就能很快定位到这个 json 文件属于哪一次分桶记录 


>process_item 中按页满即写（或用 JsonLinesItemExporter 追加写），close_spider 只做剩余 flush，并对每页写盘加 try/except + 原子写（临时文件 + os.replace），保证一页失败不影响其他页。

确实需要加入 try ... except 以及原子写，同时需要对响应内容的格式进行校验，并对写入过程进行异常处理，确保一页写入失败不影响其他页。

写入 json 文件过程是否会导致整个进程被阻塞 ？

程序是否会因为文件写入而变得缓慢 ？ 解决方案是什么 ？如何解决呢 ？

**文件名**
把 os.makedirs 挪进 __init__，让 runner 直接实例化时也建目录；同时对空串/None 做校验。



