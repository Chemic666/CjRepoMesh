# CjRepoMesh Linux增强客户端交付包

源码集分阶段构建会按实际`cjc`的选项能力选择公共CHIR输入形式：旧工具链使用位置参数，支持新选项的工具链保留`--common-part-chir`。探测仅在需要前阶段制品时发生并缓存结果；不凭版本号猜测。探测失败或输出无法识别时明确报错，普通构建不增加这一步。仍须使用匹配SDK，不代表完整Maple或所有编译器版本已验收。

本包包含已有增强版 `cjpm`、两份匹配的仓颉运行库、启动脚本、校验器及许可；可选团队版另含固定的任务准备器和示例模板。不包含SDK、cjpm工具源码、实际仓库配置、令牌或客户端缓存。接收方无需编译cjpm工具源码；构建和打包仓颉项目仍需要匹配的完整工具链。

当前验收环境为Linux amd64、Ubuntu22.04、Python3.10+。系统需要通常的glibc、libstdc++及libgcc；不随包替换系统库。不是Windows原生客户端，不保证其他Linux发行版或全新主机兼容。

清单在解析前按实际字节有界读取，最多读取1MiB+1字节；`manifest.json`超过1MiB时以固定消息拒绝，不继续文件摘要检查或Docker操作，也不修改输入。恰好上限及现有清单格式保持兼容。此项不是精确总内存、JSON深度/复杂度配额或恶意并发替换保护；旧工具包不会自动获得修复，须领取并核对完整新包。

## 接收与校验

通过可信渠道取得交付目录及其清单/归档SHA-256，复制或解包到自己的目录。不要混入 `.env`、源码或缓存；校验器会拒绝未知文件、符号链接及重解析点。

在交付目录执行：

```bash
python3 verify.py
./run.sh --help
```

离线来源查看修订后的包也可无SDK读取项目目录已有记录：

```bash
/path/to/client-bundle/run.sh repo explain meshdep --recorded
```

命令从当前目录的 `cjpm-provenance.json` 读取，不联系记录中的仓库，不更改记录；只读副本亦可。默认/项目仓库配置仍须有效，保留原配置错误拒绝、记录格式及安全地址校验。它展示已记录的来源和摘要，不重新验证包文件，也不能证明构建成功。旧c12及此前客户端仍需SDK才能执行此命令，应核对产物摘要。

启动器每次先核对固定文件的大小、SHA-256及二进制平台，再为本进程设置运行库路径并直接执行cjpm，保留参数和退出码。不会写入系统PATH、系统动态库配置或证书存储。不要只把run.sh复制到别处；需要通过完整路径调用它。

清单能发现传输损坏，不能独立证明发行者身份；核对可信渠道提供的清单摘要。若改动了包内文件，应重新取得经过验证的完整交付包，不应修改清单来忽略损坏。

## 开发者与CI使用

文件校验、`--help` 及精确的 `repo explain <包名> --recorded` 不需要完整SDK。其他命令包括 `-v`、在线解释、仓库诊断、编译/运行、`bundle`、测试和lint仍需要匹配工具链，不能把本包说成完全脱离SDK的独立客户端。客户端使用SDK1.1.3及静态stdx1.1.3.1构建；eb89bb64增量及宏依赖修复候选另在隔离的官方SDK1.2.0上验证，使用该候选的SDK1.2包时需加载1.2.0完整SDK。旧9d35739f包继续对应原SDK1.1.3验证范围。构建版本、运行库和验收范围见源码仓库[固定候选清单](https://github.com/Chemic666/CjRepoMesh/blob/main/docs/candidate-acceptance.md)，不同产物的成绩不能互换。本包不会下载SDK或扩展库，缺少工具链时保留真实失败，不伪造编译器输出。

在已加载工具链的任务环境中，从项目目录通过交付包的完整路径调用：

```bash
/path/to/client-bundle/run.sh repo doctor
/path/to/client-bundle/run.sh build
/path/to/client-bundle/run.sh repo explain company::teamhello --recorded
```

读取与发布凭据由受保护的任务环境注入，项目配置只用 `token-env` 引用；每个任务使用自己的HOME和缓存。发布任务用发布令牌，消费任务只用读取令牌。不要将凭据写进本包、URL、命令参数或提交到仓库。

脚本图与主图需要不同完整来源批准时，先查询 `run.sh repo supports script-source-baseline-v1`，再同时设置 `CJREPOMESH_SOURCE_BASELINE` 和 `CJREPOMESH_SCRIPT_SOURCE_BASELINE` 为各自独立审核的v1文件绝对路径。未设置脚本变量保持原行为；脚本变量为空或未配置主变量会拒绝。两类图仍各自精确匹配，不合并批准集合；两份文件都必须远离各次分析的最终/临时来源输出。已缓存/已重定位脚本不因此强制重分析，多个不同脚本图也不会自动选择不同批准。详见[源码仓库中的完整约束](https://github.com/Chemic666/CjRepoMesh/blob/main/docs/repository-source-baseline.md)。

包含来源基线修订的客户端可在CI设置 `CJREPOMESH_SOURCE_BASELINE=/protected/team-source-baseline.json` 后构建。文件是独立审核的来源记录副本（formatVersion整数1、完整packages及字符串字段、64位小写SHA-256），应在项目输出之外受保护且只读，不能由当前任务自动批准。最终选中的仓库包集合、版本、仓库名、URL和摘要必须全部匹配（含传递依赖及选中的替换项）；在本次制品下载前拒绝失配，索引访问可能先发生，热缓存也检查。未设置保持旧行为；设置为空、文件错误/超过1MiB或使用来源输出及其临时文件/规范路径别名均拒绝。相对路径按当前依赖分析根目录解释，推荐绝对路径。旧ba9b及此前客户端会忽略该变量，不能仅靠配置证明检查已启用。

来源基线不是发布者签名、缓存再验真或脚本沙箱，不覆盖Git/本地输入，不保证检查前零代码执行。保护工具链、仓库配置和工作目录；硬链接/恶意并发替换不在保证内。独立脚本/多模块可能产生不同依赖图，继承同一完整基线时会分别比较；当前f433客户端已验证选定的工作空间与脚本分图场景，不代表任意嵌套/增量脚本均兼容。实际范围以源码仓库对应产物的验证记录为准。

运行状态修复后的客户端在应用失败时使 `cjpm run` 返回1，成功返回0，不再错误报告完成；这不是原样转发应用退出码。需要精确保留应用状态（例如7）时，仍先 `build` 再直接运行应用产物，参照源码仓库的开发者/只读CI示例。旧af35及此前交付包尚无此修复，核对产物摘要。包内不包含服务端；服务端离线包默认仅本机HTTP监听。HTTPS与CA、跨主机接入仍需各自验收，不能关闭严格校验或假定本包提供HTTPS网关。

## 可选团队版：离线准备任务

清单声明 `capabilities.teamPreparation = "single-use-cold-v1"` 的21文件包提供 `prepare-team.py`，不需要检出源码仓库。入口先校验完整客户端、准备器、守卫及全部模板，再创建外部新任务目录。整个包可搬移或只读挂载，不写Python字节码；未知能力、缺失/损坏/额外文件或链接会拒绝。不要直接绕过入口执行team目录中的辅助文件。

从任意目录运行，填写实际获准地址和独立核对的公开CA摘要（使用系统信任时可省去两个CA选项）：

```bash
python3 /opt/cjrepomesh-client/prepare-team.py --role publisher \
  --registry https://registry.example.invalid:8443 \
  --ca-file /protected/approved-ca.pem --ca-sha256 <approved-ca-sha256> \
  --output /work/new-publisher
python3 /opt/cjrepomesh-client/prepare-team.py --role consumer --single-use \
  --registry https://registry.example.invalid:8443 \
  --ca-file /protected/approved-ca.pem --ca-sha256 <approved-ca-sha256> \
  --output /work/new-consumer
```

目录准备只需Python3.10+，不读取令牌、不联系仓库、不生成来源批准或安装CA。输出必须是包外尚不存在的新目录；已有文件、目录和链接拒绝，准备失败现场保留且不留下最终run.sh，下次选择另一个新目录。新任务源码副本保留属主读写权限，即使原交付模板只读；不更改原包或其他用户权限。团队示例发布/消费固定的 `company::teamhello 1.0.0`，不是任意项目的配置向导。

执行时加载已有匹配SDK/stdx，将 `CJREPOMESH_CJPM` 指向本包run.sh；发布任务仅注入 `CJREPO_PUBLISH_TOKEN`，消费任务仅注入 `CJREPO_READ_TOKEN`，均不把秘密放进命令行或文件。单次消费者还需 `CJREPOMESH_SOURCE_BASELINE` 指向外部独立批准文件。然后在对应新任务目录执行 `bash run.sh`。独立审核应核对发布元数据和可信CJP摘要；不要从本次消费输出自动批准。失败保留真实退出状态与现场；发布同一版本冲突不是成功。

单次任务在构建前核对固定仓库配置、空HOME和无旧缓存/输出，再原子领取，领取后成功/失败都拒绝复用；下一次用新目录。消费者应用不继承示例读写凭据，但构建仍能读取仓库，不能据此称构建沙箱。CA仅用于本任务进程，来源检查不保证索引前拒绝、不验真旧解包缓存。具体角色与来源语义见包内 `team/README.md`；其源码路径命令可用本包入口和相同参数替换。

旧八文件包不含此能力，仍可使用原客户端入口；应取得新的完整团队包，不能只把几个脚本塞进旧包或修改清单。静态能力标记和文件摘要不认证发布者，须核对可信渠道提供的归档/清单SHA-256。

## 制作端

从源码仓库执行，输入必须为已有的匹配Linux产物与SDK运行库：

```bash
python3 deployment/client/package.py \
  --cjpm /path/to/enhanced/cjpm \
  --runtime-dir /path/to/cangjie/runtime/lib/linux_x86_64_cjnative \
  --output /path/to/new-client-bundle
```

默认仅复制八份交付文件（包括manifest.json）；追加 `--include-team` 制作21文件团队版，增加固定准备入口及12份准备器/模板文件，由清单能力选择严格文件集合。不执行输入二进制、不读取客户端配置、令牌或缓存。制作端接受明确指定的SDK输入链接并复制其解析后的普通文件，包内不保留链接；接收端拒绝包内链接。输出路径必须不存在，包括不能是已有悬空链接，已有目录不会被覆盖。制作失败现场保留，下次选择新的输出目录。以tar等保留Linux执行权限的方式交付，并记录归档与清单摘要。

包内LICENSE为项目许可；随附运行库来自已有仓颉SDK，其许可信息应结合SDK发行说明确认。本包不包含完整SDK或第三方系统工具链。此交付件仍为本地试用候选，实际结果和限制以源码仓库验证记录为准。

## 解包源码缓存再校验

新版客户端首次校验归档并解包后写入旁置receipt，再次使用时核对目录/文件集合、内容摘要与选中归档摘要。源码变化、链接、receipt缺失或损坏会拒绝复用并保留文件；正常完整缓存仍可离线使用。旧版无receipt缓存不会自动信任，请在 `cangjie-repo.toml` 选一个新的 `[repository.cache].path`，从预期仓重新暖机，不删除旧目录来掩盖问题。

仓库安装在独立临时副本中构建，避免把生成的target和锁文件写回已校验源码。这是源码缓存一致性检查，不防同权限同时改写源码和receipt，也不校验生成的编译产物。并行任务使用各自独立缓存。实现与验证入口见源码仓库 `docs/cache-integrity.md`。
