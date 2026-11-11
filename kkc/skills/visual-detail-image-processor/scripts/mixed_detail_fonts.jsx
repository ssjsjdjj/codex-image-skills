/* Apply the original JPG character map to a single editable Photoshop text layer. */
function loadDetailMixedFonts(postScriptNames) {
    postScriptNames = postScriptNames || {};
    var required = {
        cn: postScriptNames.cn || "FZLTZHK--GBK1-0",
        latin: postScriptNames.latin || "G8321-Medium",
        one: postScriptNames.one || "KocoDetailFangYuan-SemiBold"
    };
    var faces = {};
    var missing = [];
    for (var role in required) {
        for (var index = 0; index < app.fonts.length; index++) {
            var candidate = app.fonts[index];
            if (candidate.postScriptName === required[role]) {
                faces[role] = candidate;
                break;
            }
        }
        if (!faces[role]) missing.push(required[role]);
    }
    if (missing.length) throw new Error("Photoshop 缺少详情页混排字体 " + missing.join("、"));
    return faces;
}

function detailMixedFontForCharacter(character, faces) {
    if (character === "1" || character === "%") return faces.one;
    if (/^[A-Za-z0-9 .+\-]$/.test(character)) return faces.latin;
    return faces.cn;
}

function applyDetailMixedFonts(layer, faces) {
    if (layer.kind !== LayerKind.TEXT) throw new Error("混排目标必须是原生文字图层 " + layer.name);
    var key = stringIDToTypeID;
    var textKey = key("textKey");
    var rangesKey = key("textStyleRange");
    var styleKey = key("textStyle");
    var postScriptKey = key("fontPostScriptName");
    var fromKey = key("from");
    var toKey = key("to");
    var read = new ActionReference();
    read.putProperty(key("property"), textKey);
    read.putIdentifier(key("layer"), layer.id);
    var descriptor = executeActionGet(read).getObjectValue(textKey);
    var contents = descriptor.getString(textKey);
    if (!contents || /^\s*$/.test(contents)) return false;

    var oldRanges = descriptor.getList(rangesKey);
    var newRanges = new ActionList();
    var changed = false;
    for (var i = 0; i < oldRanges.count; i++) {
        var range = oldRanges.getObjectValue(i);
        var start = range.getInteger(fromKey);
        var end = range.getInteger(toKey);
        var style = range.getObjectValue(styleKey);
        var oldFont = style.hasKey(postScriptKey) ? style.getString(postScriptKey) : "";
        var position = start;
        while (position < end) {
            // Preserve paragraph breaks and Photoshop's trailing insertion style.
            var character = contents.charAt(position);
            var face = character && character !== "\r" && character !== "\n" ?
                detailMixedFontForCharacter(character, faces) : null;
            var name = face ? face.postScriptName : oldFont;
            var next = position + 1;
            while (next < end) {
                var following = contents.charAt(next);
                var followingName = following && following !== "\r" && following !== "\n" ?
                    detailMixedFontForCharacter(following, faces).postScriptName : oldFont;
                if (followingName !== name) break;
                next++;
            }
            var updatedRange = oldRanges.getObjectValue(i);
            updatedRange.putInteger(fromKey, position);
            updatedRange.putInteger(toKey, next);
            if (face && name !== oldFont) {
                var updatedStyle = updatedRange.getObjectValue(styleKey);
                updatedStyle.putString(postScriptKey, name);
                updatedStyle.putString(key("fontName"), face.family);
                updatedStyle.putString(key("fontStyleName"), face.style);
                updatedStyle.putBoolean(key("fontAvailable"), true);
                updatedRange.putObject(styleKey, updatedRange.getObjectType(styleKey), updatedStyle);
                changed = true;
            }
            newRanges.putObject(oldRanges.getObjectType(i), updatedRange);
            position = next;
        }
    }
    if (!changed) return false;
    descriptor.putList(rangesKey, newRanges);
    var write = new ActionDescriptor();
    var target = new ActionReference();
    target.putIdentifier(key("layer"), layer.id);
    write.putReference(key("null"), target);
    write.putObject(toKey, key("textLayer"), descriptor);
    executeAction(key("set"), write, DialogModes.NO);
    return true;
}
