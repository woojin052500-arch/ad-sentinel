function clickLog(name) { fetch('/clicked/' + name); }
function landing(onEnter) {
  document.getElementById('app').innerHTML =
    '<div class="hero" style="height:90vh;display:flex;flex-direction:column;align-items:center;justify-content:center">' +
    '<h1>회원가입 없이, 바로 익명.</h1>' +
    '<a class="cta" href="javascript:enterSite()" style="font-size:22px;padding:20px 48px;border:1px solid #555">' +
    '지금, 익명으로 시작하기 &gt;</a></div>' +
    '<nav class="side"><a href="#about">About</a> <a href="#faq">FAQ</a></nav>';
  window.enterSite = function () {
    clickLog('enter');
    document.getElementById('app').innerHTML = '<p>로딩 중...</p>';
    setTimeout(onEnter, 800);
  };
}
function footer() {
  document.write('<footer><a href="/terms.html">이용약관</a> <a href="/privacy.html">개인정보처리방침</a></footer>');
}
