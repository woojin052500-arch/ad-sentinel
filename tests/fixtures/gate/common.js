function clickLog(name) {
  fetch('/clicked/' + name);
}
function requireEntry() {
  if (document.cookie.indexOf('entered=1') < 0) location.href = 'index.html';
}
