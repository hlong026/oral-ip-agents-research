# 文档索引

本目录按文档用途重新分层。原始文档均保留，只调整存放位置与内部相对链接。

## 分类

| 目录                 | 用途                                                                      |
| -------------------- | ------------------------------------------------------------------------- |
| `product/`           | 市场调研、产品定位、功能需求清单。                                        |
| `architecture/`      | 核心模块、视频合成、前端 IA、全栈架构、剪辑/封面/字幕方案和开源技术参考。 |
| `engineering/`       | 具体开发任务书、接口说明和阶段性修复开发计划。                            |
| `operations/`        | 真实链路验收、Go/No-Go 决策、灰度验收、生产切换和 Gate 收口记录。         |
| `design/prototypes/` | 可打开的 HTML 原型。当前 UI 原型在 `design/prototypes/ui-mockup/`。       |
| `design/references/` | PDF、截图、审计图和原型导出参考资料。                                     |

## 当前权威资料

当前实现、上线与验收口径优先看：

- [16 - 生产切换上线检查清单](operations/16-生产切换上线检查清单.md)
- [17 - Gate 4 发布工程验收记录](operations/17-Gate4发布工程验收记录.md)
- [18 - Gate 5 桌面端与 IM 收口验收记录](operations/18-Gate5桌面端与IM收口验收记录.md)
- [06 - 最终开发文档](architecture/06-最终开发文档.md)
- [14 - 视频剪辑方案 - 封面与字幕系统设计](architecture/14-视频剪辑方案-封面与字幕系统设计.md)

这些文档记录了生产门禁、真实链路边界、桌面端与 IM 的 Go/No-Go 状态，以及当前剪辑/封面/字幕方案。

## 历史资料关系

- `product/01`、`product/02` 是需求和市场输入，用于理解产品范围，不直接代表当前上线状态。
- `architecture/03`、`architecture/04`、`architecture/05` 是早期技术与界面方案输入；后续实现口径以 `architecture/06`、`operations/16`、`operations/17`、`operations/18` 为准。
- `engineering/07`、`engineering/08`、`engineering/09`、`engineering/10` 是开发任务和阶段计划，用于追溯任务来源；其中涉及 IM 或第三方私有协议的内容需同时参考 `operations/12` 的 Go/No-Go 决策。
- `operations/11`、`operations/12`、`operations/13` 是阶段验收与灰度门禁记录；外部供应商、真实账号、生产域名和连续灰度证据仍以实际采集结果为准。

## 设计资料

- HTML 原型入口：[design/prototypes/ui-mockup/index.html](design/prototypes/ui-mockup/index.html)
- 剪辑台 V2：[design/prototypes/ui-mockup/editor-v2.html](design/prototypes/ui-mockup/editor-v2.html)
- 封面设计系统：[design/prototypes/ui-mockup/cover-designer.html](design/prototypes/ui-mockup/cover-designer.html)
- UI 原型手册 PDF：`design/references/口播IP智能体-UI原型手册.pdf`
- UI 审计截图：`design/references/ui-mockup-audit/`
