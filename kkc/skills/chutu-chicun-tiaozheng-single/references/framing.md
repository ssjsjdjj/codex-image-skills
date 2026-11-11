# 逐张版用途、取景与确认命令

主图main尺寸多选800x800、1440x1440、750x1000或自定义；场景scene多选750x1000、800x800、800x1200或自定义。仅出明确所选尺寸。

主图和场景图均可直接使用JPG、PNG或已有PSD，同单照片与PSD不混合。默认Python调整尺寸，并额外交付每款每尺寸一份含1—N图片的PSD，无需将输入照片先转PSD。PNG保留格式/alpha；PSD未指定成品格式默认JPG并告知。

任务单delivery包含kind、style_id、out_dir、sizes及max_bytes=500000；jobs写真实input和逐图观察确定的focus/crop_box/protect_box。默认图片每尺寸1—N，PSD款号_尺寸。不要用固定坐标代替逐图构图。

一份PSD含多图时，仅按用户明确范围建立不同source_layers的job；白底含对应商品和真实背景层，透明不加背景。未选范围不自行拆图。平坦pixel及位图蒙版按实际能力保留；复杂PSD范围与PS提取限制见[delivery.md](delivery.md)。

```powershell
python scripts/resize_assets.py review-start --spec "<本批任务单.json>"
python scripts/resize_assets.py review-next --review "<ID>"
```

第一次next先预检整批所有待处理候选。scale=max(目标宽/实际取景宽,目标高/实际取景高)>1时聚合提示原尺寸、取景框、目标、倍率和可能模糊/变软，建议PS，由用户选PS或继续Python。所需选择齐备前不生成目标预览。选择仅绑定当前源内容、取景和尺寸；依据变化失效。PS不能保证找回缺失细节，PSD格式本身不提高画质。

```powershell
python scripts/resize_assets.py review-select-backend --review "<ID>" --backend python --size "1440x1440" --confirmation-file "<真实选择原文.txt>"
python scripts/resize_assets.py review-next --review "<ID>"
```

需要修改当前张时，patch例如{"focus":[0.5,0.42]}；null删除可选项。修改后重新next展示当前预览，不能用旧digest确认。

```powershell
python scripts/resize_assets.py review-adjust --review "<ID>" --patch "<当前张调整.json>"
python scripts/resize_assets.py review-next --review "<ID>"
python scripts/resize_assets.py review-confirm --review "<ID>" --digest "<当前最新digest>" --confirmation-file "<本张真实确认.txt>"
python scripts/resize_assets.py review-next --review "<ID>"
```

每确认一张才进入下一张。所有源图和全部所选尺寸逐张确认后：

```powershell
python scripts/resize_assets.py batch --review "<ID>"
python scripts/resize_assets.py batch --review "<ID>" --resume
```

resume只复用本批哈希一致的已完成结果，不覆盖未知同名文件。图片≤500000字节，PSD/TXT不限。禁止整批预览、整批确认和用风格授权跳过逐张人工确认。
