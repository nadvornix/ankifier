function checkAll(selector){
    $(selector).prop('checked', !$(selector).prop("checked"));
}

if ((e.ctrlKey || e.metaKey) && (e.keyCode == 13 || e.keyCode == 10)) {
    document.forms[2].submit();
}
