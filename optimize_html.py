with open('templates/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    if lines[i].strip() == '<style>':
        new_lines.append('<link rel="stylesheet" href="/static/css/style.css">\n')
        while i < len(lines) and lines[i].strip() != '</style>':
            i += 1
        i += 1
        continue
    elif lines[i].strip() == '<script>' and i > 1000:
        new_lines.append(lines[i])
        i += 1
        while i < len(lines) and 'let currentScheduleList' not in lines[i]:
            new_lines.append(lines[i])
            i += 1
        new_lines.append('</script>\n')
        new_lines.append('<script src="/static/js/app.js"></script>\n')
        while i < len(lines) and lines[i].strip() != '</script>':
            i += 1
        i += 1
        continue
    new_lines.append(lines[i])
    i += 1

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('优化完成！')
