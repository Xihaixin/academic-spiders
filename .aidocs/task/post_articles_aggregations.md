# 获取筛选条件

- 请求 URL: https://pubscholar.cn/hky/open/resources/api/v1/articles/aggregations
- 请求方法：POST

**负载**：
```json
{
    "page": 1,
    "size": 10,
    "order_field": "date",
    "order_direction": "desc",
    "user_id": "c84069ed4e4270f9897e3a07acb81355",
    "lang": "zh",
    "aggregations": {
        "type": "",
        "subject": "",
        "year": "",
        "keyword": "",
        "collection": "",
        "lang": "C",
        "source": "",
        "correspAuthor": "",
        "funding": "",
        "institution": "",
        "license": ""
    }
}
```

响应结果是一个 json ，对应的键即为请求体中 aggregations 里面元素的键，而响应体中的值则反映了首页的可选项。

我们将请求体 "lang" 属性的值设置为 "C", 在响应体中具体表现是如下：

```json
"lang":{
    "alias": "语种",
    "selected_aggregation": [
        "C"
    ],
    "aggregations":[
        {
            "origin_key": "C",
            "value": 74540267,
            "key": "中文"
        }
    ]
}
```

与其它属性相比，"lang" 的 selected_aggregation 不为空。访问下面的 json 文件获取[响应结果](./response.json)

## 问题是什么 ？

我们在开发环境中使用 scrapy crawl pubscholar_v1 启动爬虫，将数据存放在 academicdb 中，一共抓取到 1 万条数据。爬虫所使用的参数：

1. startpage: 1
2. pagesize: 50

主要是为了获取中文期刊数据，所以请求头中 "lang" 属性设置为 "C". 根据结果可以推断出网站一共有 74540267 条数据，但是我们的爬虫在 page = 200 的时候就无法获取到数据了。此时返回的响应是 200，但是具体的数据为空。

```json
response.status:200
response.text: '{"total":0,"is_last":true,"content":[]}'

```

所以，接下来就想到一种策略：既然我们已经获取到查询项的可选择列表，那么就可以通过遍历的方式来获取大部分数据。

**因此需要验证一件事情，当爬虫轮换查询参数后，网站是否仍然会限制同一个用户所能获取的最大数据量 ？**

如果上面的验证通过，那么接下来最重要的两个设计就是：
1. 对爬虫所获取数据的查重方法
2. 日志：记录爬虫每次爬取数据时的参数设置
3. 爬虫获取数据并进行翻页的边界是什么 ？
4. 如何让爬虫实现端点重续 ？

## 项目需求

- 再次验证当 lang = C, page > 200 后的爬虫响应情况
- 获取 aggregation 请求的响应结果，并使用 json 文件进行保存
- 设计一个简单的记录器，可以调度多条件查询参数的执行情况

如果通过多种查询条件进行组合，来遍历目标网站的数据，那么就需要涉及组合的规则，同时还需要记录处理的进度，以及已经发送过的查询参数是什么。[这也是一个设计重点]


## 设计实现方案

爬虫每次运行第一个请求就是对 aggregations 接口发送的 POST 请求。拿到响应数据之后，按照一定规则从里面获取筛选项进行遍历。

