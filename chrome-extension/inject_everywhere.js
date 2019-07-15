// alert("hello");
// document.body.style.background = 'yellow';
window.onload = function(){ 
 
    document.body.onclick = function (e) {
        if (e.ctrlKey) {
            sel = window.getSelection();
            var word = sel.toString(); 
            if((word.length > 0) && (word.length < 100)){
                if(e.target.contains(getSelection().anchorNode)){
                    var range = document.createRange();
                    range.setStart(sel.anchorNode, sel.anchorOffset);
                    range.setEnd(sel.focusNode, sel.focusOffset);
                    var backwards = range.collapsed;
                    range.detach();

                    // modify() works on the focus of the selection
                    var endNode = sel.focusNode, endOffset = sel.focusOffset;
                    sel.collapse(sel.anchorNode, sel.anchorOffset);

                    var direction = [];
                    if (backwards) {
                        direction = ['backward', 'forward'];
                    } else {
                        direction = ['forward', 'backward'];
                    }

                    sel.modify("move", direction[0], "character");
                    sel.modify("move", direction[1], "sentence");
                    sel.extend(endNode, endOffset);
 
                    sel.modify("extend", direction[1], "character");
                    sel.modify("extend", direction[0], "sentence");
                    var sentence = window.getSelection().toString(); 
                    sel.collapseToStart();
                    window.open('http://ankireader.jirinadvornik.com/word?s='+sentence+'&w='+word, '_blank'); 
                    // window.open('http://localhost:5000/word?s='+sentence+'&w='+word, '_blank'); 
                }
            }
            // var selRange = word.getRangeAt(0);
        }
    }

};
