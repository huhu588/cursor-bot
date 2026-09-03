# Sand 璧勬牸棰嗗彇鍣紙SandClaimer锛?
鎵归噺缁?Cursor 璐﹀彿棰嗗彇 **Grok Bot锛圫and锛?* 璧勬牸鐨勬闈㈠皬宸ュ叿銆俰OS 鐜荤拑娴呰摑椋庣晫闈紝鑷姩璇嗗埆涓ょ token 鏍煎紡锛屾敮鎸佸鍏?JSON銆佹壒閲忛鍙栥€佹壒閲忔坊鍔犺处鍙枫€?
## 鍔熻兘

- **涓ょ token 鑷姩璇嗗埆**锛歚access_token`锛圝WT锛宍eyJ...`锛変笌 `ws token`锛坄user_01XXXX::eyJ...`锛屽嵆 WorkosCursorSessionToken锛夈€?- **瀵煎叆鏂瑰紡**锛氱洿鎺ョ矘璐达紙姣忚涓€涓紝鍙贩鎺掞級銆佺矘璐?`cursor_accounts_*.json` 鍐呭銆佹垨銆屽鍏ユ枃浠躲€嶉€変竴涓?澶氫釜 JSON銆傛寜 user id 鑷姩鍘婚噸銆?- **鎵归噺棰嗗彇**锛氶€愪釜棰嗗彇骞跺疄鏃舵樉绀烘瘡琛岀姸鎬侊紱宸插紑閫氱煭璺€佸洟闃熷彿鑷姩甯?`teamId`銆佷釜浜哄彿璧拌瘯鐢ㄣ€佸厤璐瑰彿鏍囪銆岄渶缁戝崱銆嶃€?- **鍒锋柊鐘舵€?*锛氬彧璇绘煡璇㈡瘡涓处鍙风殑 Sand 棰濆害涓庢槸鍚﹀紑閫氥€?- **缁曡繃鏈満 DNS 鍔寔**锛氬唴缃?DoH锛?.1.1.1锛夎В鏋?`cursor.com` / `api2.cursor.sh` 鐪熷疄 IP锛屽嵆浣挎湰鏈鸿窇鐫€浼氬姭鎸佽繖浜涘煙鍚嶇殑缃戝叧锛堝 cgw锛変篃鑳界洿杩炵湡瀹?Cursor銆?
## 杩愯锛堝紑鍙戯級

```bat
python -m pip install -r requirements.txt
python app.py
```

> Windows 闇€瑕?**Edge WebView2 杩愯鏃?*锛圵in10/11 涓€鑸嚜甯︼紱缂哄け鏃跺埌寰蒋瀹樼綉瑁呫€孍vergreen WebView2 Runtime銆嶏級銆?
## 鎵撳寘锛圢uitka 缂栬瘧 + 瀹夎鍖咃級

鍙屽嚮鎴栧懡浠よ杩愯锛?
```bat
build.bat
```

浜х墿锛?
- `nuitka-out\SandClaimer.exe` 鈥斺€?鍗曟枃浠剁豢鑹茬増锛屽弻鍑诲嵆鐢ㄣ€?- `installer\SandClaimer-Setup-2.0.2.exe` 鈥斺€?涓枃瀹夎鍚戝锛岃鍒?Program Files 骞跺缓寮€濮嬭彍鍗?妗岄潰蹇嵎鏂瑰紡銆?
`build.bat` 浼氫緷娆★細瑁呬緷璧?鈫?淇ˉ Nuitka 鐨?pywebview 鎻掍欢 鈫?鐢熸垚鍥炬爣 鈫?Nuitka 缂栬瘧 鈫?Inno Setup 鎵撳畨瑁呭寘銆?
### 涓轰粈涔堢敤 Nuitka锛堣€岄潪 PyInstaller锛?
- **鍚姩鏇村揩**锛歅ython 婧愮爜琚紪璇戞垚 C/鏈哄櫒鐮侊紝涓嶆槸瑙ｉ噴鎵ц鐨?`.pyc`銆?- **澶╃劧娣锋穯/鍔犲瘑**锛氫骇鐗╂槸鍘熺敓鏈哄櫒鐮侊紝婧愮爜涓嶅彲杩樺師锛沷nefile 杩愯鏃舵妸璐熻浇瑙ｅ帇鍒颁复鏃剁洰褰曞啀鎵ц锛堢浉褰撲簬鍔犲瘑灏佽锛夛紝姣?PyInstaller 鐨勫彲鐩存帴瑙ｅ寘 `.pyc` 寮哄緱澶氥€?- 闇€瑕佹湰鏈鸿鏈?**MSVC锛圴S2022 Build Tools锛?* 渚?Nuitka 缂栬瘧锛涢娆＄紪璇戣緝鎱紝涔嬪悗璧?clcache 缂撳瓨浼氬揩寰堝銆?
> `patch_plugin.py`锛歂uitka 4.1.3 鐨?pywebview 鎻掍欢鍦?Windows 鐧藉悕鍗曢噷婕忎簡 pywebview 6.2.x 鏂板鐨?`webview.platforms.win32`锛屼細瀵艰嚧鎵撳寘鍚?winforms 鍚庣璧蜂笉鏉ャ€傝鑴氭湰骞傜瓑鍦版妸瀹冭ˉ杩涚櫧鍚嶅崟锛宍build.bat` 宸茶嚜鍔ㄨ皟鐢ㄣ€?>
> `ChineseSimplified.isl`锛氬畨瑁呭悜瀵肩殑绠€浣撲腑鏂囪瑷€鍖咃紙Inno Setup 榛樿涓嶅惈锛夈€?
## 棰嗗彇瑙勫垯锛堜笌 Cursor 瀹樻柟涓€鑷达級

- **浠樿垂璐﹀彿**锛圥ro+ / Ultra / Team锛夛細鐩存帴寮€閫氾紝鏃犻渶缁戝崱銆?- **鍏嶈垂璐﹀彿**锛氶鍙栭渶鍏堥獙璇佷俊鐢ㄥ崱锛屽伐鍏蜂細鏍囪銆岄渶缁戝崱銆嶏紙濡傝繑鍥為獙璇侀摼鎺ヤ細涓€骞剁粰鍑猴級銆?- **鍥㈤槦璐﹀彿**锛氳蛋鍥㈤槦閫氶亾骞惰嚜鍔ㄥ甫涓?`teamId`锛堜粠 `get-me` 璇诲彇锛夈€傚洟闃熺骇寮€閫氭槸鍚﹁鐩栧叏閮ㄦ垚鍛樺骇浣嶏紝鍙栧喅浜?Cursor 渚х瓥鐣ャ€?
## 鐢ㄥ埌鐨勫畼鏂规帴鍙ｏ紙鍧囧疄娴嬬‘璁わ級

| 鐢ㄩ€?| 鏂规硶 | 绔偣 | 閴存潈 |
|---|---|---|---|
| 鏌ラ搴?| POST | `api2.cursor.sh/aiserver.v1.DashboardService/GetSandUsageStatus` | Bearer accessToken |
| 鏌ヨ祫鏍?| POST | `cursor.com/api/dashboard/get-sand-access-status` | 浼氳瘽 cookie |
| 鍙?teamId | POST | `cursor.com/api/dashboard/get-me` | 浼氳瘽 cookie |
| 涓汉棰嗗彇 | POST | `cursor.com/api/dashboard/start-sand-trial` | cookie + Origin |
| 鍥㈤槦棰嗗彇 | POST | `cursor.com/api/dashboard/request-sand-team-access`锛坆ody `{teamId}`锛?| cookie + Origin |

## 瀹夊叏

- token 鍙湪鏈満鍐呭瓨涓庢湰鏈衡啍Cursor 瀹樻柟涔嬮棿浣跨敤锛屼笉涓婁紶浠讳綍绗笁鏂规湇鍔°€?- 璇峰嬁鎶婂惈 token 鐨?JSON 鎴栨湰宸ュ叿鏃ュ織鍒嗕韩缁欎粬浜恒€?
## 椤圭洰缁撴瀯

```
sand-claimer/
鈹溾攢 app.py                # pywebview 鍏ュ彛 + JS 妗ユ帴
鈹溾攢 sand_api.py           # Cursor Sand 鏌ヨ/棰嗗彇
鈹溾攢 accounts.py           # token/JSON 瀵煎叆涓庤处鍙疯〃
鈹溾攢 sand_patch.py         # 鏈満 Cursor 瀹㈡埛绔ā寮忚ˉ涓?/ 鍥為€€
鈹溾攢 resolve.py            # DoH 缁曡繃 DNS 鍔寔
鈹溾攢 web/                  # 鐜荤拑椋?UI锛坕ndex.html / style.css / app.js锛?鈹溾攢 make_icon.py          # heguang 鍥炬爣 鈫?澶氬昂瀵?icon.ico
鈹溾攢 patch_plugin.py       # 淇ˉ Nuitka pywebview 鎻掍欢锛堣ˉ win32锛?鈹溾攢 installer.iss         # Inno Setup 瀹夎鍖呰剼鏈?鈹溾攢 ChineseSimplified.isl # 瀹夎鍚戝绠€浣撲腑鏂囪瑷€鍖?鈹溾攢 icon.ico              # 搴旂敤鍥炬爣锛堝鐢?heguang锛?鈹溾攢 requirements.txt
鈹斺攢 build.bat             # 涓€閿細缂栬瘧 + 鎵撳畨瑁呭寘
```

