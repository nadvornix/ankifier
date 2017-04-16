// alert("hello");
// document.body.style.background = 'yellow';
window.onload = function(){ 


document.body.onclick = function (e) {
   if (e.ctrlKey) {
        var selObj = window.getSelection().toString(); 
        if (selObj){
            window.open('http://localhost:5000/word?w='+selObj+'&s=SEN', '_blank'); 
        }
        // var selRange = selObj.getRangeAt(0);
   }
}

};
