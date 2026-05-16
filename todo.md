A. 同 session 的上下文继承
测什么：
第一轮提到的信息
第二轮是否能继续引用
是否带对上一轮的正确 history
例如：
第 1 轮：记住我叫 yhz
第 2 轮：我刚刚叫什么
要测：
第二轮是否带了前序消息
是否不是空上下文
是否最终回答引用了前文

B. 新 session 的历史隔离
测什么：
创建新 session 后
不能把旧 session 的 turns/history 继承过来
例如：
Session A：我叫 yhz
Session B：我刚刚叫什么
要测：
Session B 不应该看到 Session A 的对话历史
如果回答引用了 A，就说明污染了

C. 同 session 的 tool/memory 行为稳定性
测什么：
多轮里是否重复不必要调工具
是否错误复用上一轮工具结果
是否把上一轮的 memory context 错注入当前轮

D. 多轮 + 异步回写
测什么：
第一轮结束后异步富化回写 turn
第二轮读取 history 时，看到的是不是“正确的新版本 turn”
有没有读到旧版本或半写入状态