function clickLog(name) { fetch('/clicked/' + name); }
function goHome(name) { clickLog(name); location.href = '/'; }
