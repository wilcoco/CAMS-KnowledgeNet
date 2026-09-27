from nightwish.rendering import render_answer


def test_markdown_formats_answer_without_active_html_or_remote_images():
    html=render_answer('''## 도입 순서

1. **원문 보존**
2. 검토

| 종류 | 의미 |
| --- | --- |
| 사실 | 원문 확인 |

```yaml
rule: review
```

<script>alert(1)</script><img src=x onerror=alert(1)>
[위험](javascript:alert%281%29)
![원격 이미지](https://example.org/tracker.png)
[원문](https://example.org/source)
[[관련 개념]]
''')
    assert '<h2>' in html and '<table>' in html and '<ol>' in html and '<pre>' in html
    assert '<script>' not in html and '<img' not in html and 'href="javascript:' not in html
    assert 'rel="noopener noreferrer"' in html
    assert 'class="wl" data-link="관련 개념"' in html


def test_wikilink_attributes_and_code_are_not_executable():
    html=render_answer('[[" onclick="alert(1)]]\n\n`[[not a link]]`')
    assert 'data-link="&quot; onclick=&quot;alert(1)"' in html
    assert '<code>[[not a link]]</code>' in html
