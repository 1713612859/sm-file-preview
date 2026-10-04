// 边界样本：验证抹注释状态机的豁免与保护语义。预期命中清单见 fixture/README.md。

/* 单行块注释里的 console.log('x') 与 eval('y') 都不应告警（注释内容被抹掉） */
const localUrl = 'http://localhost:8080/debug';
const w3Url = 'http://www.w3.org/2000/svg';

// FIXME: 这里临时绕过，下个迭代处理
const tpl = `select * from t_order where id=${1}`;
const s = 'not a comment: http://x.example.com/path';
