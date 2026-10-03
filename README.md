# ELF 发布包依赖预检后端

基于 FastAPI 0.115 + pyelftools 0.32 的 Linux 发布包依赖预检服务。
静态解析 x86-64 小端 ELF64 动态程序/共享库，**不执行**待检文件，也**不调用 ldd**，
不读取 `ld.so.cache`，所有路径均限制在发布根之内（绝不读宿主 /lib、/usr/lib）。

## 运行

```bash
.venv/bin/python -m uvicorn app.main:app --port 8123
```

## API

`POST /api/precheck`

```json
{
  "root": "/path/to/release-root",
  "entry": "/bin/app",
  "lib_dirs": ["/lib", "/opt/lib"],
  "max_file_size": 67108864,
  "max_nodes": 256
}
```

- `root`：发布根（宿主路径）；`entry`、`lib_dirs` 为**虚拟绝对路径**（相对发布根）。
- 响应含 `ok` / `incomplete` / `nodes` / `edges` / `diagnostics`；
  每条边报告引用对象、库名、搜索候选、选中路径与缺失版本。

## 支持的子集（说明）

- 仅 x86-64（EM_X86_64）、小端、ELF64 的 ET_EXEC/ET_DYN 动态对象；其余报错。
- 解析 DT_NEEDED / DT_SONAME / DT_RPATH / DT_RUNPATH 及 GNU VERDEF/VERNEED。
- 搜索目录仅支持虚拟绝对路径与 `$ORIGIN` 展开；其他变量、空项、相对路径报错。
- 无斜杠依赖搜索顺序：有效 RPATH（沿加载链继承，凡持 RUNPATH 的对象不贡献 RPATH）
  → 请求 lib_dirs → 直接引用者的 RUNPATH → /lib → /usr/lib。
  带斜杠依赖仅支持虚拟绝对路径。
- 按 NEEDED 顺序广度优先建图；同 SONAME 复用首次对象；循环依赖保留全部边。
- 核对引用方 VERNEED 中的非弱版本存在于选中库的 VERDEF；缺失仅记录，不改选同名库。
- 符号链接在发布根内解析：绝对目标按虚拟绝对路径重映射；检测循环与越界逃逸。
- 文件大小与图节点数超限即截断并标记 `incomplete`；缺库/架构/版本不符保留其余分支诊断，整体不通过。

## 自测与演示

```bash
bash tests/make_fixtures.sh /tmp/precheck-release   # gcc 生成真实 ELF 夹具
.venv/bin/python -m pytest tests/ -q                # 单元/集成测试
bash tests/demo.sh                                  # 启动服务并用 curl 展示报告
```

