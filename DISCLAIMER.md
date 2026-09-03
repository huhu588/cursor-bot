# 免责声明

> 下载、编译、运行或以任何方式使用本项目，即表示你已阅读并同意本声明的全部内容。如不同意，请勿使用并删除全部副本。

## 一、项目性质

本项目是作者出于**技术学习与研究**目的编写的桌面工具，用于研究以下技术细节：桌面端 Web UI 框架（pywebview / WebView2）的集成与打包、Windows 客户端本地登录态（SQLite / state.vscdb）的读取、Connect + protobuf 接口的调用与解析、DoH 解析与 hosts 修复等。

本项目**仅供学习、研究、技术交流与个人自测使用**，不面向生产环境，不提供任何形式的服务或代客操作。

## 二、与第三方无任何关联

本项目与 Anysphere / Cursor、xAI / Grok 及其任何关联公司**没有隶属、赞助、授权、认证或合作关系**，也未获得上述任何一方的背书。

"Cursor""Grok"等名称、标识与商标归各自权利人所有。本项目中出现这些名称，仅为客观、必要地描述所研究的技术对象（描述性使用），不构成商标使用或来源混淆。

## 三、服务条款与风险提示（重要，请勿跳过）

本工具会在本机执行以下操作：读写 Cursor 客户端的本地登录态、修改客户端资源文件、修改系统 hosts、重置本机标识，并使用你提供的凭据调用 Cursor 官方接口批量查询与领取资格。

**上述行为可能违反 Cursor 的服务条款（Terms of Service）或可接受使用政策。**由此可能产生的后果包括但不限于：

- 账号被风控、限制功能、暂停或永久封禁；
- 订阅被取消、已领取的资格被回收、余额或额度损失；
- 本机 Cursor 客户端无法启动、配置或数据损坏；
- 因违反合同（服务条款）而承担的相应责任。

是否使用、如何使用，完全由使用者自行判断和决定；**一切风险与后果由使用者自行承担**。作者不对任何账号损失、数据损失、服务中断、经济损失或法律后果承担任何责任。

在使用前请务必备份重要数据，并优先在你自己拥有、且有权处置的账号与设备上测试。

## 四、禁止用途

不授权、不建议、也明确反对将本项目用于：

- 任何商业用途，包括但不限于对外收费、代刷代领、账号或资格的买卖与倒卖；
- 批量注册、批量养号、绕过付费门槛以获取商业服务；
- 访问、控制或处置**不属于你本人或未获得授权**的账号、设备与系统；
- 任何其他违反法律法规、侵犯他人合法权益的行为。

使用者应自行遵守所在国家或地区的法律法规以及相关服务的条款。若你所在地区的法律禁止此类工具，请立即停止使用并删除全部副本。

## 五、不提供任何担保

本项目按**"现状"（AS IS）**提供，不作任何明示或默示的担保，包括但不限于对适销性、特定用途适用性、准确性、可用性及不侵权的担保。

作者不保证功能可用、结果正确或持续可用（上游接口随时可能变更而导致工具失效），亦不承担因使用或无法使用本项目而产生的任何直接、间接、偶然、特殊、惩罚性或后果性损害赔偿责任。

## 六、数据与隐私

本项目**不设服务端，不收集、不上传任何用户数据**，没有遥测与统计上报。

账号凭据仅保存在使用者本机（`%LOCALAPPDATA%\SandClaimer\accounts.json`），且只在本机与 Cursor 官方接口之间使用。读取本机客户端登录态时以只读方式打开数据库。请自行妥善保管相关文件，**不要把含 token 的 JSON 或运行日志分享给他人**。

## 七、第三方组件

本项目依赖的第三方开源组件（pywebview、httpx、requests、websocket-client、zstandard、Pillow、pefile、Nuitka 等）版权归其各自作者所有，并按其各自的许可证条款分发。

## 八、侵权处理与下架

若任何权利人认为本项目的内容侵犯其合法权益，请通过本仓库的 Issue 或邮件与作者联系并说明具体情形。作者将在核实后**及时删除相关内容或下架整个仓库**，无需诉讼程序。

## 九、代码贡献与转载

本仓库仅作技术研究记录。转载、引用或二次分发时请保留本声明；因二次分发或修改产生的任何后果，由分发者与使用者自行承担。

---

# Disclaimer (English)

This project is a personal **educational and research** tool. It is **not affiliated with, sponsored by, endorsed by, or authorized by** Anysphere / Cursor, xAI / Grok, or any of their affiliates. All trademarks belong to their respective owners and are used here descriptively only.

**Use at your own risk.** The tool reads and modifies local client state, modifies the system hosts file, resets local machine identifiers, and calls vendor APIs with credentials that you supply. **Such use may violate the vendor's Terms of Service** and may result in account restriction, suspension, permanent ban, loss of subscription or entitlements, or data loss. The author accepts **no liability** for any such outcome.

The software is provided **"AS IS", without warranty of any kind**, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose and non-infringement. In no event shall the author be liable for any claim, damages or other liability arising from, out of or in connection with the software or its use.

Commercial use, resale, account trading, bulk account farming, and any unauthorized access to accounts, devices or systems **are not permitted**. You are solely responsible for complying with all applicable laws and with the terms of any service you interact with.

**No data collection:** there is no server component and no telemetry. Credentials stay on your own machine.

**Takedown:** if you are a rights holder and believe this repository infringes your rights, please open an issue or contact the author; the content or the entire repository will be removed promptly upon verification, without the need for legal action.

By downloading, building or running this project, you acknowledge that you have read and accepted this disclaimer. If you do not agree, do not use it and delete all copies.
