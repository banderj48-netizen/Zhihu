# 角色卡初始化 API

实现基础流程：授权记录 → 异步导入任务 → 进度查询 → 画像草稿 → 用户修改 → revision 乐观锁 → 不可变版本 → 标准 `chara_card_v2` 导出。

当前任务处理使用 FastAPI `BackgroundTasks` 模拟五个阶段，后续替换为队列时保持 `fetching / storing_raw / extracting / review / completed` 语义。知乎 OAuth、原始数据存储、LLM 抽取和向量检索应作为适配器接入；token 只存后端密钥服务。

画像中的 memory 必须有 `depth: deep|middle|shallow`、来源引用和确认状态；`share=false` 不导出。分身虚拟互动不能升级为主人现实经历。

运行：

```text
cd backend
pip install -e .
uvicorn app.main:app --reload
```
