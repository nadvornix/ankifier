// alert("hello");
// document.body.style.background = 'yellow';
window.onload = function(){ 


document.body.onclick = function (e) {
   if (e.ctrlKey) {
        var selObj = window.getSelection().toString(); 
        if (selObj){
            window.open('http://localhost:5000/word?s=SEN&w='+selObj, '_blank'); 
        }
        // var selRange = selObj.getRangeAt(0);
   }
}

};
