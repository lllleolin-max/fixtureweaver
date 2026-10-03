# FixtureWeaver

Create reduced, deterministic SQLite test databases by closing seed rows over foreign keys and masking identifier classes across their linked columns. The output is a separate database checked by SQLite and your declared consumer queries.

This is a bounded fixture tool for quiescent test copies. Stable pseudonyms retain linkage. It provides no anonymity or privacy proof.

```sh
python -m pip install .
fixtureweaver source.db fixture.db --plan plan.json
```

## 中文

FixtureWeaver 从种子行出发，补齐外键依赖，并将同一标识类的关联列统一映射，生成一个独立的缩减测试数据库。真实 SQLite 约束与用户声明的查询共同验收结果。用途是避免抽样和逐列替换导致测试数据无法联表；不保证匿名化。
