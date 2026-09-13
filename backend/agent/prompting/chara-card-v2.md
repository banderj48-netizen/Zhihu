# chara_card_v2 兼容层

Agent 使用内部 digital_twin_v1 的投影结果。标准字段保持字符串语义，TwinLoop 专属的 schema、版本、证据和记忆元数据放入 extensions.twin。

普通酒馆不执行条件召回；完整三层记忆行为由 TwinLoop Agent runtime 负责。
