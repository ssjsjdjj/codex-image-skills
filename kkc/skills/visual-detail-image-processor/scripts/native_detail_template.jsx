/* Native bindings for 产品信息T.psb. Keep the mother template's text and geometry. */
function getNativeDetailTemplate(doc) {
    if (doc.width.as("px") !== 790 || doc.height.as("px") !== 11657) return null;
    var product = doc.layerSets.getByName("产品信息 拷贝 2");
    var info = product.layerSets.getByName("组 844");
    var sizeGroup = product.layerSets.getByName("尺码").layerSets.getByName("组 830")
        .layerSets.getByName("组 1266").layerSets.getByName("组 1265");
    var quickGroup = product.layerSets.getByName("尺码快选");
    var size = nativeDetailTypeLayers(sizeGroup);
    var headers = [];
    var columns = [];
    for (var i = 0; i < size.length; i++) {
        if (size[i].textItem.contents.indexOf("\r") >= 0) columns.push(size[i]);
        else headers.push(size[i]);
    }
    var quickColumns = nativeDetailTypeLayers(quickGroup.layerSets.getByName("组 1004"));
    for (i = quickColumns.length - 1; i >= 0; i--) {
        if (quickColumns[i].name === "身高cm/体重kg") quickColumns.splice(i, 1);
    }
    headers.sort(nativeDetailLeftToRight);
    columns.sort(nativeDetailLeftToRight);
    quickColumns.sort(nativeDetailLeftToRight);
    var weights = nativeDetailTypeLayers(quickGroup.layerSets.getByName("组 841 拷贝 3"));
    if (headers.length !== 6 || columns.length !== 6 || quickColumns.length !== 8 || weights.length !== 1) {
        throw new Error("产品信息T 的可编辑尺码表图层结构与固定母版不一致。");
    }
    return {
        info: [
            info.artLayers.getByName("KQ26201 "),
            info.artLayers.getByName("100%"),
            info.artLayers.getByName(" 聚酯纤维"),
            info.artLayers.getByName("110-170")
        ],
        sizeHeaders: headers,
        sizeColumns: columns,
        quickColumns: quickColumns,
        quickWeights: weights,
        quickLabel: quickGroup.artLayers.getByName("身高/体重"),
        quickUnits: quickGroup.layerSets.getByName("组 1004").artLayers.getByName("身高cm/体重kg")
    };
}

function nativeDetailTypeLayers(group) {
    var layers = [];
    for (var i = 0; i < group.artLayers.length; i++) {
        var layer = group.artLayers[i];
        if (layer.kind === LayerKind.TEXT && layer.visible) layers.push(layer);
    }
    return layers;
}

function nativeDetailLeftToRight(first, second) {
    return first.bounds[0].as("px") - second.bounds[0].as("px");
}

function nativeDetailFontTargets(template) {
    return template.info.concat(template.sizeHeaders, template.sizeColumns, template.quickWeights,
        template.quickColumns, [template.quickLabel, template.quickUnits]);
}

function updateNativeDetailTables(template, tables) {
    if (!tables) return 0;
    var size = tables["03选尺码"];
    var quick = tables["05尺码快选"];
    var count = 0;
    var col;
    if (size) {
        nativeDetailCheckMatrix("03选尺码", size, 6);
        for (col = 0; col < 6; col++) {
            template.sizeHeaders[col].textItem.contents = nativeDetailCell(size[0][col]);
            template.sizeColumns[col].textItem.contents = nativeDetailColumn(size, col);
        }
        count++;
    }
    if (quick) {
        nativeDetailCheckMatrix("05尺码快选", quick, 8);
        template.quickLabel.textItem.contents = nativeDetailCell(quick[0][0]);
        var weightStrip = template.quickWeights[0];
        var weightCenters = [187, 271, 359, 445, 533, 617, 704];
        template.quickWeights = [];
        for (col = 1; col < 8; col++) {
            var heading = weightStrip.duplicate();
            heading.textItem.contents = nativeDetailCell(quick[0][col]);
            heading.textItem.justification = Justification.CENTER;
            var position = heading.textItem.position;
            heading.textItem.position = [UnitValue(weightCenters[col - 1], "px"), position[1]];
            heading.name = "体重区间 " + col;
            template.quickWeights.push(heading);
        }
        weightStrip.remove();

        // Several original columns start below the first row. Move their
        // anchors to the first row before inserting the complete row matrix.
        var initialOffsets = [0, 0, 0, 0, 67, 67, 132, 198];
        for (col = 0; col < 8; col++) {
            var column = template.quickColumns[col];
            if (initialOffsets[col]) column.translate(0, -initialOffsets[col]);
            column.textItem.contents = nativeDetailColumn(quick, col);
        }
        count++;
    }
    return count;
}

function nativeDetailCheckMatrix(name, matrix, columns) {
    if (matrix.length < 2 || matrix.length > 8) {
        throw new Error(name + "需要 1 至 7 行数据。");
    }
    for (var row = 0; row < matrix.length; row++) {
        if (matrix[row].length !== columns) {
            throw new Error(name + "第 " + (row + 1) + " 行需要 " + columns + " 列以匹配产品信息T的固定表格。");
        }
    }
}

function nativeDetailCell(value) {
    var text = value === null || value === undefined ? "" : String(value);
    if (/[\r\n]/.test(text)) throw new Error("表格单元格请填写单行内容。");
    return text || " ";
}

function nativeDetailColumn(matrix, column) {
    var lines = [];
    for (var row = 1; row < matrix.length; row++) lines.push(nativeDetailCell(matrix[row][column]));
    return lines.join("\r");
}
