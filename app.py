from flask import Flask, render_template, request, jsonify
import json
import os
from pathlib import Path

app = Flask(__name__)

# Arquivos
ARQ_VOTOS = 'votos.json'
ARQ_CONFIG = 'config.json'

# Valores padrão
PADRAO_CANDIDATOS = ['Aluizo', 'Andre', 'Fabio', 'Guilherme', 'Lucas', 'Michael', 'Thiago', 'Walisson']
PADRAO_TURNOS = ['1º turno', '2º turno']
PADRAO_CONFIG = {
    "candidatos": PADRAO_CANDIDATOS,
    "turnos": PADRAO_TURNOS,
    "turno_atual": "1º turno",
    "presentes": 0,
    "votaram": 0
}

@app.before_request
def handle_head_requests():
    if request.method == 'HEAD':
        return '', 200


def ler_json_seguro(path, padrao):
    """Lê um JSON e retorna padrao se vazio ou inválido."""
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(padrao, f, indent=4, ensure_ascii=False)
        return padrao.copy()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            conteudo = f.read().strip()
            if not conteudo:
                raise ValueError
            return json.loads(conteudo)
    except Exception:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(padrao, f, indent=4, ensure_ascii=False)
        return padrao.copy()


def inicializar_arquivos():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    votos = ler_json_seguro(ARQ_VOTOS, {c: 0 for c in config['candidatos']})

    for c in config['candidatos']:
        if c not in votos:
            votos[c] = 0

    to_remove = [k for k in votos if k not in config['candidatos']]
    for k in to_remove:
        votos.pop(k)

    with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
        json.dump(votos, f, indent=4, ensure_ascii=False)

    with open(ARQ_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


@app.route('/')
def index():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    candidatos = config['candidatos']
    return render_template('index.html', candidatos=candidatos)


@app.route('/votar', methods=['POST'])
def votar():
    """Recebe JSON: { "votos": ["Nome1","Nome2", ...] }"""
    dados = request.get_json(force=True)
    votos_recebidos = dados.get('votos', [])
    if not isinstance(votos_recebidos, list) or len(votos_recebidos) == 0:
        return jsonify({'mensagem': 'Nenhum voto recebido!'}), 400
    if len(votos_recebidos) > 6:
        return jsonify({'mensagem': 'Você só pode votar em até 6 candidatos!'}), 400

    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    candidatos_validos = config['candidatos']
    votos = ler_json_seguro(ARQ_VOTOS, {c: 0 for c in candidatos_validos})

    invalidados = []
    for v in votos_recebidos:
        if v in votos:
            votos[v] += 1
        else:
            invalidados.append(v)

    # Incrementa contador de pessoas que votaram
    config['votaram'] = config.get('votaram', 0) + 1

    with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
        json.dump(votos, f, indent=4, ensure_ascii=False)

    with open(ARQ_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    msg = f'Votos confirmados: {", ".join([v for v in votos_recebidos if v not in invalidados])}'
    if invalidados:
        msg += f' (ignorados: {", ".join(invalidados)})'
    return jsonify({'mensagem': msg})


@app.route('/resultados', methods=['GET'])
def resultados():
    votos = ler_json_seguro(ARQ_VOTOS, {c: 0 for c in PADRAO_CANDIDATOS})
    return jsonify(votos)


@app.route('/admin')
def admin_page():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    return render_template('admin.html', config=config)


@app.route('/admin/data', methods=['GET'])
def admin_data():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    votos = ler_json_seguro(ARQ_VOTOS, {c: 0 for c in config['candidatos']})
    presentes = config.get('presentes', 0)
    votaram = config.get('votaram', 0)
    faltam = max(presentes - votaram, 0)

    percent = {}
    for c in config['candidatos']:
        if presentes > 0:
            pct = (votos.get(c, 0) / presentes) * 100
        else:
            pct = 0
        percent[c] = round(pct, 2)
    total = sum(votos.values())

    return jsonify({
        "presentes": presentes,
        "votaram": votaram,
        "faltam": faltam,
        "turnos": config.get('turnos', []),
        "turno_atual": config.get('turno_atual', ''),
        "candidatos": config['candidatos'],
        "votos": votos,
        "total_votos": total,
        "percent": percent
    })


@app.route('/admin/update_config', methods=['POST'])
def admin_update_config():
    dados = request.get_json(force=True)
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    votos = ler_json_seguro(ARQ_VOTOS, {c: 0 for c in config['candidatos']})

    if 'presentes' in dados:
        try:
            config['presentes'] = int(dados['presentes'])
        except Exception:
            pass

    if 'turnos_text' in dados:
        turnos = [t.strip() for t in dados['turnos_text'].split(',') if t.strip()]
        if turnos:
            config['turnos'] = turnos
            if config.get('turno_atual') not in turnos:
                config['turno_atual'] = turnos[0]

    if 'turno_atual' in dados:
        if dados['turno_atual'] in config.get('turnos', []):
            config['turno_atual'] = dados['turno_atual']

    if 'candidatos_text' in dados:
        novos = [c.strip() for c in dados['candidatos_text'].split(',') if c.strip()]
        if novos:
            novos_votos = {c: votos.get(c, 0) for c in novos}
            with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
                json.dump(novos_votos, f, indent=4, ensure_ascii=False)
            config['candidatos'] = novos

    if dados.get('reset_votos'):
        zeros = {c: 0 for c in config['candidatos']}
        with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
            json.dump(zeros, f, indent=4, ensure_ascii=False)
        config['votaram'] = 0  # também reseta contagem de quem votou

    with open(ARQ_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    return jsonify({'mensagem': 'Configurações atualizadas com sucesso.'})


if __name__ == '__main__':
    import os
    inicializar_arquivos()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

