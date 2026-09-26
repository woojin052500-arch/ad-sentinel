function clickLog(name) { fetch('/clicked/' + name); }
function requireEntry() {
  if (document.cookie.indexOf('entered=1') < 0) location.href = '/index.html';
}
function footer() {
  document.write(
    '<footer class="site-footer"><nav>' +
    '<a href="/terms.html">이용약관</a> | <a href="/privacy.html">개인정보처리방침</a> | ' +
    '<a href="/guide.html">서비스 안내</a> | <a href="/stats.html">통계</a> | ' +
    '<a href="/youth.html">청소년보호정책</a> | <a href="/contact.html">제휴문의</a>' +
    '</nav><p>© 커뮤월드. All rights reserved.</p></footer>');
}
