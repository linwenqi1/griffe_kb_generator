# Griffe KB builder

此目录使用仓库中的 `griffe` submodule 和 uv，从 Python 包源码生成 schema-v4 KB。
这里只包含构建流程，不读取旧 KB，也不执行比较。

## 安装

从仓库根目录运行。`uv` 直接使用 `../griffe` 的源码；更新 submodule 后重新运行
`uv sync --locked`。

PowerShell：

```powershell
git submodule update --init griffe
Set-Location kb_builder
uv sync --locked
```

Linux shell：

```bash
git submodule update --init griffe
cd kb_builder
uv sync --locked
```

## 构建自己的包

[manifest.template.json](manifest.template.json) 是只含占位符的通用模板。
先复制为本地 `manifest.json`，按下文规范填写，然后选择一个**尚不存在**的输出目录。
`manifest.json` 和 `experiments/` 已被 Git 忽略。

PowerShell（在 `kb_builder` 目录中）：

```powershell
if (-not (Test-Path manifest.json)) { Copy-Item manifest.template.json manifest.json }
# 编辑 manifest.json，替换全部占位符
$output = 'experiments/run-' + (Get-Date -Format 'yyyyMMddHHmmssfff')
uv run --locked python -m kb_builder --manifest manifest.json --output-dir $output --no-raw
```

Linux shell（在 `kb_builder` 目录中）：

```bash
if [ ! -e manifest.json ]; then cp manifest.template.json manifest.json; fi
# 编辑 manifest.json，替换全部占位符
output="experiments/run-$(date -u +%Y%m%d%H%M%S%N)"
uv run --locked python -m kb_builder --manifest manifest.json --output-dir "$output" --no-raw
```

可重复使用 `--package` 和 `--version` 过滤 manifest 中的记录。省略
`--no-raw` 时还会保存 Griffe 原始模型。

## Manifest 格式与填写规范

Manifest 必须是 UTF-8 编码的 JSON **数组**，每个对象对应一个包的一个版本。
不要加入旧 KB 路径或比较字段。

| 字段 | 必填 | 填写规范 |
| --- | --- | --- |
| `package` | 是 | 分发包名称，用于输出目录和 KB 的 `package` 字段。 |
| `version` | 是 | 与源码对应的版本字符串。 |
| `import_name` | 是 | Python 导入名；可能与 `package` 不同，例如 `more-itertools` 对应 `more_itertools`。 |
| `source_root` | 是 | 解压后的源码根目录，必须是已存在的目录。 |
| `search_path` | 是 | **包含顶层导入包或模块的目录**，必须存在且位于 `source_root` 内。 |
| `source_archive` | 否 | 源码压缩包路径；用于记录来源和计算哈希，不用于加载代码。 |
| `archive_sha256` | 否 | 压缩包的 64 位十六进制 SHA-256；填写时须同时填写 `source_archive`，运行时会校验。 |

路径可以是绝对路径，也可以相对于 **manifest 文件所在目录**，与运行命令时的
当前目录无关。JSON 中建议使用 `/`；Windows 反斜杠 `\` 必须写成 `\\`。

### `search_path` 怎么填

Griffe 从 `search_path` 查找 `import_name`。它应指向导入包目录的**父目录**，
而非导入包目录本身。例如源码采用 `src` 布局：

```text
source_root               = /path/to/package-1.0
search_path               = /path/to/package-1.0/src
import_name               = package
search_path / import_name = /path/to/package-1.0/src/package
```

此时应填 `src`，不能填 `src/package`。如果源码直接是
`source_root/package/__init__.py`，则 `search_path` 可与 `source_root` 相同。
单文件模块同理：对于 `source_root/src/name.py`，填写
`search_path=source_root/src`、`import_name=name`。

## 可直接运行的 Bokeh 示例

`example/` 中直接放置完整的 `bokeh 3.2.2` 解压源码树和压缩包，没有额外的
包名/版本号/`source` 外层目录：[manifest.example.json](manifest.example.json)
在本目录下，指向这些真实文件，可直接运行。

```text
kb_builder/
├── manifest.example.json
└── example/
    ├── bokeh-3.2.2/          # 包含 src/bokeh、tests、pyproject.toml 等
    └── bokeh-3.2.2.tar.gz
```

示例记录如下。注意 `search_path` 是 `example/bokeh-3.2.2/src`，
而导入包目录是它下面的 `bokeh`。

```json
[
  {
    "package": "bokeh",
    "version": "3.2.2",
    "import_name": "bokeh",
    "source_root": "example/bokeh-3.2.2",
    "search_path": "example/bokeh-3.2.2/src",
    "source_archive": "example/bokeh-3.2.2.tar.gz",
    "archive_sha256": "b2959b8524d69ec4e7886bc36407445f0a92e1f19530d3bfc4045236a1b7a6ff"
  }
]
```

PowerShell（在 `kb_builder` 目录中）：

```powershell
$output = 'experiments/bokeh-example-' + (Get-Date -Format 'yyyyMMddHHmmssfff')
uv run --locked python -m kb_builder --manifest manifest.example.json --output-dir $output --no-raw
```

Linux shell（在 `kb_builder` 目录中）：

```bash
output="experiments/bokeh-example-$(date -u +%Y%m%d%H%M%S%N)"
uv run --locked python -m kb_builder --manifest manifest.example.json --output-dir "$output" --no-raw
```

此示例已验证生成 20,165 条签名。

## 输出文件

每条成功记录生成 `<output-dir>/<package>/<version>/griffe_kb.json.gz`；
运行记录位于 `<output-dir>/build_manifest.json`。不加 `--no-raw` 时，
同一版本目录下还会生成 `griffe_raw.json.gz`。工具不生成包级多版本汇总文件。

### `griffe_kb.json.gz` 的格式

该文件是 gzip 压缩的 UTF-8 JSON，解压后只有一行。下面列的是
用 `manifest.example.json` 生成的 **Bokeh 文件的实际键顺序**；
为便于看清层级，只省略了列表内容和大部分值：

```text
griffe_kb.json.gz
└── JSON
    ├── metadata
    │   ├── adapter_schema: 4
    │   ├── alias_edges                 # 数组，本次有 4729 条
    │   │   └── [0]: {exposed_fqn, resolved, resolved_fqn, target_fqn}
    │   ├── allow_inspection
    │   ├── archive
    │   ├── archive_sha256
    │   ├── distribution
    │   ├── filtered_instance_attribute_count
    │   ├── filtered_instance_attributes
    │   ├── filtered_non_runtime_member_count
    │   ├── filtered_non_runtime_members
    │   ├── generator: "griffe"        # 在 alias_edges 后面，不在文件开头
    │   ├── griffe_version
    │   ├── import_name
    │   ├── recovered_exposed_fqn_count
    │   ├── recovered_exposed_fqns
    │   ├── resolve_aliases
    │   ├── resolve_external
    │   ├── return_shape_source
    │   ├── scope_counts
    │   ├── search_path
    │   ├── signature_count: 20165
    │   ├── skipped_module_alias_descent_count
    │   ├── skipped_module_alias_descents
    │   ├── source_import_overlay_edge_count
    │   ├── source_import_overlay_edges
    │   ├── source_import_overlay_parse_error_count
    │   ├── source_import_overlay_parse_errors
    │   ├── source_root
    │   ├── unresolved_alias_count
    │   ├── unresolved_aliases
    │   ├── unresolved_source_import_edge_count
    │   └── unresolved_source_import_edges
    ├── package: "bokeh"
    ├── schema_version: 4
    └── versions                       # API 签名从这里开始
        └── "3.2.2"
            └── "bokeh.client.util.server_url_for_websocket_url"  # FQN
                ├── bases
                ├── callable_kind
                ├── canonical_fqn
                ├── fqn
                ├── instance_result_known
                ├── line
                ├── parameters
                │   └── [0]: {annotation, default, kind, name, required}
                ├── parameters_known
                ├── return_annotation
                ├── return_shape: "value"
                ├── scope
                └── source_file
```

上面并没有把 `generator` 或 `return_shape` 凭空加进文件：前者确实在
`metadata` 中，只是排在很长的 `alias_edges` 后面；后者位于
`versions["3.2.2"][FQN]` 中。`source_file` 相对于 manifest 中的
`search_path`。`build_manifest.json` 是另一个运行记录文件，不是 KB 本体。

### 如何读取和使用

无需先手工解压。Python 的 `gzip.open` 负责解压，`json.load` 将一行 JSON
解析为字典。把下面的 `kb_path` 改为自己的输出路径：

```python
import gzip
import json
from pathlib import Path

kb_path = Path("<output-dir>/bokeh/3.2.2/griffe_kb.json.gz")
with gzip.open(kb_path, "rt", encoding="utf-8") as stream:
    kb = json.load(stream)

print(kb.keys())  # metadata, package, schema_version, versions
signatures = kb["versions"]["3.2.2"]
print(len(signatures))  # 此示例为 20165
fqn = "bokeh.client.util.server_url_for_websocket_url"
api = signatures[fqn]
print(api["return_shape"])  # value
print(json.dumps(api, ensure_ascii=False, indent=2))
```

查 API 时使用 `versions[版本号][FQN]`；`metadata.alias_edges` 记录别名解析
过程，不是签名清单。若想查看整份文件的可读排版，可对解析后的 `kb` 使用
`json.dumps(kb, ensure_ascii=False, indent=2)`；这只改变显示方式，不改变 KB 数据。
