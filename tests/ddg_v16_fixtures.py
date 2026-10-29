"""Finite synthetic fixtures; no claim of captured/live DuckDuckGo HTML."""
import urllib.parse

def result(title='Title',url='https://example.com/a',snippet='Snippet',wrapper=False):
    pair=f'<a class="result__a" href="{url}">{title}</a><a class="result__snippet">{snippet}</a>'
    return '<div class="result">'+pair+'</div>' if wrapper else pair

def corpus():
    return {
      'single':(result(),8),
      'multiple':(result('One',snippet='First')+result('Two','https://example.com/b','Second'),8),
      'zero':('<p>No results</p>',8),
      'fewer':(result(),5),
      'more':(result('One')+result('Two'),1),
      'entities':(result('A &amp; B',snippet='C &#65; &lt;D&gt;'),8),
      'outbound':(result(url='/l/?uddg='+urllib.parse.quote('https://example.com/a?q=x%20y',safe='')),8),
      'empty_content':(result('',snippet=''),8),
      'inline':(result('<b>Bold</b> title',snippet='Text <em>with</em> inline'),8),
      'unicode':(result('日本 🙂',snippet='café Ελληνικά'),8),
      'duplicates':(result('One')+result('Again'),8),
      'intervening':('<div class="result"><h2 class="result__title"><a class="result__a" href="https://example.com/a">Title</a></h2><div class="extras">ignore</div><a class="result__snippet">Snippet</a></div>',8),
    }

def malicious(family,size):
    patterns={
      'openings':'<a class="result__a" href="https://example.com/a">T</a>',
      'missing_close':'<a class="result__a" href="https://example.com/a">T',
      'near_class':'<a class="result__aa" href="https://example.com/a">T</a>',
      'whitespace':' ',
      'benign':result(),
      'malformed':'<a class="result__a" href="',
    }
    p=patterns[family];return (p*((size+len(p)-1)//len(p)))[:size]
