# elfcheck — Linux 发布包依赖预检后端

基于 FastAPI 0.115.12 + pyelftools 0.32 的 ELF 依赖预检服务。**纯静态解析**，不执行待检文件，也不调用 ldd / 读取 ld.so.cache。

## 运行

    .venv/bin/python -m elfcheck          # 监听 127.0.0.1:8000

## 接口

POST /check

    {
      "release_root": "/host/path/to/release",   // 宿主机上的发布根目录
      "entry": "/app/bin/app",                    // 入口 ELF 的虚拟绝对路径
      "lib_dirs": ["/app/lib"]                    // 有序请求库目录（虚拟绝对路径）
    }

返回 {ok, incomplete, nodes, edges, diagnostics}：

- nodes：每个对象的 path / soname / needed / rpath / runpath / verdef
- edges：引用对象、库名、搜索候选 candidates、选中路径 selected、缺失版本 missing_versions
- diagnostics：missing / version / elf / path / limit 分类诊断；某一分支失败不影响其他分支，整体 ok=false

示例：

    sh examples/build_examples.sh            # 生成真实 ELF 示例树
    curl -s -X POST http://127.0.0.1:8000/check -H 'Content-Type: application/json' \
      -d '{"release_root":"'$PWD'/examples/release","entry":"/app/bin/app","lib_dirs":["/app/lib"]}'

测试：.venv/bin/python -m pytest tests

## 支持的子集

- 文件格式：ELF64、x86-64（EM_X86_64）、小端、ET_EXEC/ET_DYN；其他一律报 elf 类错误。单文件上限 64 MiB，图节点上限 256，超限置 incomplete=true。
- 路径模型：所有路径为虚拟绝对路径，映射到 release_root 之下；符号链接（含绝对目标）同样按虚拟路径解析，检测循环与越界，绝不读取宿主机库文件。
- 动态标签：解析 DT_NEEDED / DT_SONAME / DT_RPATH / DT_RUNPATH 及 GNU 版本段（VERNEED/VERDEF）。
- 搜索顺序（无斜杠依赖）：有效 RPATH → 请求 lib_dirs → 请求者 RUNPATH → /lib → /usr/lib。
  - RPATH 沿加载链继承；对象带 RUNPATH 时其 RPATH 被忽略，且 RUNPATH 只用于该对象的直接依赖。
  - 搜索目录仅支持虚拟绝对路径与 $ORIGIN 展开；$LIB 等其他变量、空项、相对路径均报错。
  - 带斜杠的依赖只支持虚拟绝对路径。
- 图构建：按 NEEDED 顺序广度优先；同一 SONAME 复用首次加载的对象；循环依赖的边完整保留。
- 版本核对：非弱 VERNEED 版本必须在选中库的 VERDEF 中；缺失只报告，不改选同名库。

## 代码结构

- elfcheck/elfparse.py — ELF 解析（pyelftools）
- elfcheck/vfs.py — 虚拟路径映射与符号链接安全
- elfcheck/resolver.py — 搜索目录与 $ORIGIN 展开
- elfcheck/graph.py — BFS 建图、依赖解析、版本核对
- elfcheck/app.py — FastAPI HTTP 层
- examples/build_examples.sh — 生成真实 ELF 示例（正常、缺版本、缺库、符号链接循环、非法 ELF）
- tests/test_check.py — pytest 自测
