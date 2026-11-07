"""Build an offline, secret-free documentation book on the archive disk."""
import html
import json
import posixpath
import re
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
DESTINATION=Path('F:/Архив/Документация ДРЕВО')


def build():
    assert (DESTINATION.parent/'.drevo/drevo.sqlite3').is_file(), 'Connect the archive drive F:'
    files=[ROOT/'docs/USER_GUIDE.md',ROOT/'README.md',*sorted((ROOT/'docs').glob('*.md')),ROOT/'PRODUCT.md',ROOT/'DESIGN.md']
    files=list(dict.fromkeys(files))
    files += sorted((ROOT/'research-template/schemas').glob('*.json'))
    anchors={p.relative_to(ROOT).as_posix():'doc-'+str(i) for i,p in enumerate(files)}
    DESTINATION.mkdir(exist_ok=True)
    def inline(text,current):
        value=html.escape(text)
        def link(match):
            label,target=match.groups()
            normalized=posixpath.normpath(posixpath.join(posixpath.dirname(current),html.unescape(target)))
            href=('#'+anchors[normalized]) if normalized in anchors else target
            return f'<a href="{href}">{label}</a>' if href.startswith(('https://','http://','#')) else label
        value=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,value)
        value=re.sub(r'`([^`]+)`',r'<code>\1</code>',value)
        return re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',value)
    def render(text,current):
        lines=text.splitlines();output=[];index=0
        while index<len(lines):
            line=lines[index]
            if line.startswith('```'):
                block=[];index+=1
                while index<len(lines) and not lines[index].startswith('```'):
                    block.append(lines[index]);index+=1
                output.append('<pre><code>'+html.escape('\n'.join(block))+'</code></pre>')
            elif line.startswith('|'):
                rows=[]
                while index<len(lines) and lines[index].startswith('|'):
                    cells=lines[index].strip().strip('|').split('|')
                    if not all(re.fullmatch(r'\s*:?-+:?\s*',cell) for cell in cells): rows.append(cells)
                    index+=1
                output.append('<div class="table"><table>')
                for number,cells in enumerate(rows):
                    tag='th' if number==0 else 'td'
                    output.append('<tr>'+''.join(f'<{tag}>{inline(c.strip(),current)}</{tag}>' for c in cells)+'</tr>')
                output.append('</table></div>');continue
            elif re.match(r'^#{1,6} ',line):
                level=min(len(line)-len(line.lstrip('#'))+2,6)
                output.append(f'<h{level}>'+inline(line.lstrip('# '),current)+f'</h{level}>')
            elif re.match(r'^\s*(?:[-*]|\d+\.) ',line):
                ordered=bool(re.match(r'^\s*\d+\.',line));tag='ol' if ordered else 'ul'
                output.append('<'+tag+'>')
                while index<len(lines) and re.match(r'^\s*(?:[-*]|\d+\.) ',lines[index]):
                    output.append('<li>'+inline(re.sub(r'^\s*(?:[-*]|\d+\.) ','',lines[index]),current)+'</li>');index+=1
                output.append('</'+tag+'>');continue
            elif line.strip():
                output.append('<p>'+inline(line,current)+'</p>')
            index+=1
        return '\n'.join(output)
    sections=[];navigation=[]
    for path in files:
        relative=path.relative_to(ROOT).as_posix()
        target=DESTINATION/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        text=path.read_text(encoding='utf-8-sig')
        title=next((line.lstrip('# ') for line in text.splitlines() if line.startswith('# ')),path.name)
        body='<pre><code>'+html.escape(text)+'</code></pre>' if path.suffix=='.json' else render(text,relative)
        sections.append(f'<article id="{anchors[relative]}"><h2>{html.escape(title)}</h2><p class="file">{html.escape(relative)}</p>{body}</article>')
        navigation.append(f'<a href="#{anchors[relative]}">{html.escape(title)}</a>')
    book='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ДРЕВО — полная документация</title><style>
body{margin:0;font:16px/1.6 "Segoe UI",sans-serif;color:#202725;background:#fafbf9}nav{position:fixed;inset:0 auto 0 0;width:260px;padding:24px;overflow:auto;background:#eef1ed;box-sizing:border-box}nav a{display:block;margin:12px 0;color:#244c38}main{margin-left:280px;max-width:1000px;padding:36px}article{padding:24px 0;border-top:1px solid #ccd4cc;scroll-margin-top:16px}h1,h2,h3,h4{line-height:1.3}p{overflow-wrap:anywhere}a{color:#24573d}code,pre{font-family:Consolas,monospace}code{background:#edf0eb;padding:2px 4px}pre{padding:16px;background:#edf0eb;white-space:pre-wrap;overflow-wrap:anywhere}pre code{padding:0}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;border:1px solid #ccd4cc;padding:8px}.table{overflow:auto}.file{font-size:13px;color:#68716b}@media(max-width:850px){nav{position:static;width:auto}main{margin:0;padding:20px}}@media print{nav{display:none}main{margin:0;padding:0;max-width:none}article{break-before:page}a{color:inherit}}
</style><nav><strong>ДРЕВО · Документация</strong>NAV</nav><main><h1>ДРЕВО — полная документация</h1><p>Офлайн-копия. Основные данные находятся на внешнем диске F:. Для чтения этого файла сервер и интернет не нужны.</p><p><a href="https://drevo-beta.vercel.app">Открыть сайт</a> · <a href="https://drevo-beta.vercel.app/ai/index.json">AI index</a></p>CONTENT</main></html>'''.replace('NAV',''.join(navigation)).replace('CONTENT',''.join(sections))
    (DESTINATION/'Открыть документацию.html').write_text(book,encoding='utf-8')
    shortcut='<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=Документация ДРЕВО/Открыть документацию.html"><a href="Документация ДРЕВО/Открыть документацию.html">Открыть полную документацию ДРЕВО</a>'
    (DESTINATION.parent/'ДОКУМЕНТАЦИЯ ДРЕВО.html').write_text(shortcut,encoding='utf-8')
    (DESTINATION/'manifest.json').write_text(json.dumps({'files':list(anchors),'format':'offline HTML and original Markdown/JSON','secrets_included':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'documentation':str(DESTINATION),'source_documents':len(files),'html_bytes':len(book.encode())},ensure_ascii=False))


if __name__=='__main__':build()
