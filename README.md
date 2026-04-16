# ArcWeaver

ArcWeaver 是一个面向 Windows 的复杂归档提取工具，专门处理普通解压软件经常失败的目录与文件集合。它不是单纯调用一次 7-Zip，而是在解压引擎之上增加了伪装归档识别、Polyglot 探测、递归处理、分卷求解、同目录快速补卷、结果整理和安全清理等流程能力。

它主要解决这类场景：

- 文件扩展名被伪装、污染或故意改坏
- 非归档文件中嵌入了可提取的归档数据
- 分卷散落在不同目录、名称不一致、尾部被污染或顺序线索残缺
- 一层解开后内部还有多层嵌套归档
- 解压成功后还需要把结果稳定落回工作目录，并安全执行清理

本项目受到开源项目 `Complex-unzip-tool v2` 的启发，但当前实现并不是对 v2 的简单延续。ArcWeaver 已按新的分层结构、流程控制方式和任务收尾规则重新整理。

## 设计目标

ArcWeaver 的目标不是盲目尝试所有可能，而是把复杂解压场景变成一个有边界、可解释、可复用的工程能力：

- 为桌面使用和脚本调用提供统一入口
- 在复杂输入下尽量自动恢复真实归档关系
- 在失败时给出明确线索，而不是只返回一次模糊报错
- 在执行删除和清理前，先保证结果已经安全落地

## 核心能力

### 1. 伪装归档识别

ArcWeaver 会同时利用文件名、文件头和强制探测结果判断目标是否本质上是归档。对于被改扩展名、插入干扰字符、故意伪装的文件，系统会建立临时别名再尝试提取。

### 2. Polyglot 与嵌入归档处理

当文件表面上是媒体、文档或其他普通文件时，ArcWeaver 可以在开启相关选项后继续探测其内部是否藏有可 carve 的归档载荷，并把这些内容重新送回提取流程。

### 3. 递归嵌套提取

一次成功提取并不会直接结束。新得到的内容会重新进入扫描与证据构建流程，直到没有新的可处理对象为止。

### 4. 分卷补救与组卷求解

对于缺卷、伪装分卷、散落分卷和命名被改坏的场景，ArcWeaver 会先建立主卷候选，再围绕候选卷进行评分、补充候选卷和重试。评分会综合考虑：

- 命名归一化后的家族特征
- token 相似度与数字线索
- 目录位置
- 文件头类型
- 推测归档类型
- 缺卷反馈
- 文件大小等辅助信号

当主卷已经明确返回缺卷反馈，且同目录下存在 `family_tokens` 完全一致的未决候选时，系统会先执行一次“同目录快速尝试”。这一步会优先利用文件名中的卷号线索补齐同组分卷，避免在明显同组的候选已经存在时，仍然先走更宽泛的跨目录评分与补卷推断。

### 5. 结果发布与安全清理

最终结果先统一发布到 `unzipped`，然后再按任务选项执行后处理：

1. 将结果提升回工作目录
2. 删除源归档
3. 删除工作目录

如果结果提升失败，后续破坏性动作不会继续执行。

## 项目结构

```text
ArcWeaver/
├─ 7z/                     # 随项目分发的 7-Zip 运行时
├─ core/                   # 核心能力层
│  ├─ api/                 # 任务入口、选项模型、任务级收尾
│  ├─ workflow/            # 递归提取主流程、失败分类、结果发布
│  ├─ multipart/           # 分卷归一化、评分、求解
│  └─ config/              # 运行配置与评分权重
├─ ui/                     # Tk 桌面图形界面
├─ ArcWeaver.spec          # PyInstaller 目录版构建描述
├─ build_exe.ps1           # 可执行程序构建脚本
├─ build_release.ps1       # 发布目录与 ZIP 打包脚本
└─ launch_desktop_app.py   # 桌面端入口
```

## 命令行用法

源码运行时，可以直接通过模块方式调用：

```powershell
python -m core D:\Sample\input_set
```

如果通过 Poetry 安装，也可以使用脚本命令：

```powershell
poetry run arcweaver D:\Sample\input_set
```


打包发布后，命令行入口是 `ArcWeaverCli.exe`：

```powershell
.\ArcWeaverCli.exe D:\Sample\input_set
```

图形界面入口仍然是 `ArcWeaver.exe`。
常见示例：

```powershell
poetry run arcweaver D:\Sample\task_a D:\Sample\task_b
.\ArcWeaverCli.exe D:\Sample\input_set
poetry run arcweaver D:\Sample\input_set -p sample-pass-1 -p sample-pass-2
poetry run arcweaver D:\Sample\input_set --password-file .\passwords.txt
poetry run arcweaver D:\Sample\input_set --delete-source --delete-working-dir
poetry run arcweaver D:\Sample\input_set --no-promote-output --json
```

常用参数：

- `-p`, `--password`：添加密码，可重复传入
- `--password-file`：从文本文件读取密码，每行一个
- `--delete-source`：结果提升成功后删除源归档
- `--delete-working-dir`：完成后删除工作目录
- `--no-promote-output`：不把结果回提到工作目录
- `--no-polyglot`：关闭 polyglot 探测
- `--no-disguised`：关闭伪装归档探测
- `--no-recycle-bin`：删除时不使用系统回收站
- `--max-depth`：递归提取深度
- `--seven-zip-path`：指定 7z.exe 路径
- `--json`：输出完整 JSON 结果

退出码约定：

- `0`：全部成功
- `1`：部分成功，仍有剩余问题
- `2`：失败或命令参数错误

## 典型工作流

### 任务规划

输入会先被规划为统一任务结构：

- `workspace_dir`
- `output_dir`
- `working_dir`

默认中间目录是 `.complex_unzip_work`，默认输出目录是 `unzipped`。

### 递归证据构建与提取

每轮扫描中，ArcWeaver 会为文件建立证据并按顺序尝试：

1. 直接按文件名归档类型提取
2. 按文件头识别结果提取
3. 对 polyglot 文件做 carve 后提取
4. 对疑似对象做强制扩展探测

### 失败分类

失败不会都混成同一类，而会进入不同候补集合：

- 主卷候选
- 未决候选
- 密码失败候选

这让后续策略可以根据失败性质分别推进。

### 分卷求解

当递归阶段没有更多新结果时，ArcWeaver 会针对主卷候选逐个建立求解任务。系统会根据当前分值选出最可能的卷组合，遇到缺卷则继续补入候选卷，遇到明显不匹配的卷则排除，成功后再回到递归提取。

对于“同目录、同家族、卷号连续但命名尾部被污染”的场景，系统会先做同目录预检，再进入常规评分流程。这样像 `sp673_1 / sp673_2 / sp673_3`，或 `sp674 (2).7z删除1 / 删除2 / 删除3` 这类文件集合，不需要等到更宽泛的候选搜索阶段，便可直接优先组卷验证。

## 适合解决的问题

ArcWeaver 在以下场景中通常表现较好：

- 文件主体仍然完整，只是扩展名、命名或目录结构被污染
- 分卷的真实数据仍在，只是主卷和分卷之间的表面关系被破坏
- 文件头仍可识别，或能通过缺卷反馈得到稳定线索
- 递归层数有限，且每一层都能被底层归档后端处理
- 需要在同一次任务里自动完成提取、整理和清理

## 适用范围

ArcWeaver 的适用范围很明确。它擅长“发现、比对、重命名、重组、验证”，但不具备“补出缺失数据”的能力。

它不能解决的典型情况包括：

- 真实卷文件物理缺失，且没有其他来源可以补齐
- 加密归档没有可用密码
- 文件已严重损坏，超出底层归档后端的可恢复范围
- 所有命名线索、头部线索、目录线索都被完全抹除，同时存在多个同样合理的候选
- 底层 7-Zip 本身不支持或支持不完整的特殊格式

换句话说，ArcWeaver 是“基于线索推断并交由后端验证”的恢复工具，不是字节级重建工具。

## 复杂场景说明

在复杂输入下，ArcWeaver 可能出现以下受限行为：

- 只能得到 `partial_success`，因为一部分内容可提取，另一部分仍缺卷或缺密码
- 能识别主卷，却无法唯一确认后续卷顺序
- 能识别出文件其实是归档，但后端返回密码错误或数据损坏
- 多个候选卷分值接近，需要依赖缺卷反馈逐轮推进，而不是一次命中

这类情况说明输入本身仍存在不确定性，系统会把这种不确定性保留下来，而不是伪装成完全成功。

## 状态语义

- `success`：完整链路执行成功，没有遗留失败候补
- `partial_success`：已经产生有效结果，但仍存在未决项、缺卷项或密码失败项
- `failed`：没有得到最终有效结果

调用方不应把 `partial_success` 当作完全成功。

## Python API

如果需要从 Python 脚本内部调用，可使用：

```python
from core import ExtractOptions, extract_task

result = extract_task(
    r"D:\Sample\input_set",
    ExtractOptions(
        passwords=["sample-pass"],
        detect_polyglot_archives=True,
        delete_source_archives=False,
        delete_working_dir=False,
        promote_output_contents_to_workspace=True,
    ),
)

print(result.extraction.status)
print(result.extraction.next_action)
print(result.extraction.extracted_files)
```

## 桌面端

启动方式：

```powershell
python launch_desktop_app.py
```

如果通过 Poetry 安装：

```powershell
poetry run arcweaver-gui
```

桌面端当前支持：

- 多文件单任务导入
- 单目录任务导入
- Polyglot 检测开关
- 结果提升开关
- 工作目录清理开关
- 回收站删除开关
- 密码词典输入
- 本次运行会话日志

## 构建与发布

安装依赖：

```powershell
poetry install
```

如果只构建桌面端：

```powershell
python -m pip install pyinstaller
```

构建目录版：

```powershell
.\build_exe.ps1
```

默认输出：

```text
dist\ArcWeaver\
```

构建单文件版：

```powershell
.\build_exe.ps1 -OneFile
```

生成发布包：

```powershell
.\build_release.ps1
```

默认发布目录形如：

```text
release\ArcWeaver-v3.0.0-windows-x64\
```

## 运行依赖

发布包中需要保留以下资源：

- `7z/7z.exe`
- `7z/7z.dll`
- `core/config/multipart_scoring.json`

## 开发说明

- `core/api` 负责任务入口、选项模型和任务级收尾
- `core/workflow` 负责流程推进、状态累积和结果发布
- `core/multipart` 负责分卷识别与求解
- 评分策略位于 `core/config/multipart_scoring.json`

建议至少验证以下内容：

- 桌面端能正常启动
- 命令行入口能正常处理文件和目录
- 分卷求解可根据缺卷反馈继续加入候选卷
- 结果提升与删除顺序符合预期
- `success`、`partial_success`、`failed` 状态判定正确

## 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE)。

## 相关文档

- [EMBEDDED_API.md](EMBEDDED_API.md)
- [EMBEDDED_DESIGN.md](EMBEDDED_DESIGN.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [OPEN_SOURCE_RELEASE_CHECKLIST.md](OPEN_SOURCE_RELEASE_CHECKLIST.md)

