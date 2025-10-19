from flask import Flask, render_template, request, jsonify
import json
import os
from pathlib import Path
app = Flask(__name__)

# Arquivos
ARQ_VOTOS = 'votos.json'
ARQ_CONFIG = 'config.json'

# Valores padrão
PADRAO_CANDIDATOS = [
    {"nome": "Aluizo"},
    {"nome": "Andre"},
    {"nome": "Fabio"},
    {"nome": "Guilherme"},
    {"nome": "Lucas"},
    {"nome": "Michael"},
    {"nome": "Thiago O"},
    {"nome": "Thiago R"},
    {"nome": "Walisson"},
]
PADRAO_TURNOS = ['1º turno', '2º turno']
PADRAO_CONFIG = {
    "candidatos": PADRAO_CANDIDATOS,
    "turnos": PADRAO_TURNOS,
    "turno_atual": "1º turno",
    "presentes": 0,
    "votaram": 0
}


def ler_json_seguro(path, padrao):
    """Lê um JSON e retorna padrao se vazio ou inválido."""
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(padrao, f, indent=4, ensure_ascii=False)
        return json.loads(json.dumps(padrao))
    try:
        with open(path, 'r', encoding='utf-8') as f:
            conteudo = f.read().strip()
            if not conteudo:
                raise ValueError
            return json.loads(conteudo)
    except Exception:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(padrao, f, indent=4, ensure_ascii=False)
        return json.loads(json.dumps(padrao))


def inicializar_arquivos():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)

    # Garante que "Voto Nulo" exista
    if not any(c['nome'] == "Voto Nulo" for c in config["candidatos"]):
        config["candidatos"].append({"nome": "Voto Nulo"})

    nomes = [c['nome'] for c in config["candidatos"]]
    votos = ler_json_seguro(ARQ_VOTOS, {n: 0 for n in nomes})

    # Ajusta estrutura
    for n in nomes:
        if n not in votos:
            votos[n] = 0
    to_remove = [k for k in votos if k not in nomes]
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
    candidatos_validos = [c['nome'] for c in config['candidatos']]
    votos = ler_json_seguro(ARQ_VOTOS, {c: 0 for c in candidatos_validos})

    invalidados = []
    for v in votos_recebidos:
        if v in votos:
            votos[v] += 1
        else:
            invalidados.append(v)

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
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    nomes = [c['nome'] for c in config['candidatos']]
    votos = ler_json_seguro(ARQ_VOTOS, {n: 0 for n in nomes})
    return jsonify(votos)


@app.route('/admin')
def admin_page():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    return render_template('admin.html', config=config)


@app.route('/admin/data', methods=['GET'])
def admin_data():
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)
    nomes = [c['nome'] for c in config['candidatos']]
    votos = ler_json_seguro(ARQ_VOTOS, {n: 0 for n in nomes})

    presentes = config.get('presentes', 0)
    votaram = config.get('votaram', 0)
    faltam = max(presentes - votaram, 0)

    percent = {}
    for n in nomes:
        pct = (votos.get(n, 0) / presentes * 100) if presentes > 0 else 0
        percent[n] = round(pct, 2)

    total = sum(votos.values())

    return jsonify({
        "presentes": presentes,
        "votaram": votaram,
        "faltam": faltam,
        "turnos": config.get('turnos', []),
        "turno_atual": config.get('turno_atual', ''),
        "candidatos": nomes,
        "votos": votos,
        "total_votos": total,
        "percent": percent
    })


@app.route('/admin/update_config', methods=['POST'])
def admin_update_config():
    dados = request.get_json(force=True)
    config = ler_json_seguro(ARQ_CONFIG, PADRAO_CONFIG)

    nomes = [c['nome'] for c in config['candidatos']]
    votos = ler_json_seguro(ARQ_VOTOS, {n: 0 for n in nomes})

    # Atualiza presentes
    if 'presentes' in dados:
        try:
            config['presentes'] = int(dados['presentes'])
        except Exception:
            pass

    # Atualiza turnos
    if 'turnos_text' in dados:
        turnos = [t.strip() for t in dados['turnos_text'].split(',') if t.strip()]
        if turnos:
            config['turnos'] = turnos
            if config.get('turno_atual') not in turnos:
                config['turno_atual'] = turnos[0]

    # Atualiza turno atual
    if 'turno_atual' in dados:
        turno_selecionado = dados['turno_atual']
        if turno_selecionado in config.get('turnos', []):
            config['turno_atual'] = turno_selecionado

    # Atualiza candidatos
    if 'candidatos_text' in dados:
        novos = [c.strip() for c in dados['candidatos_text'].split(',') if c.strip()]
        if novos:
            novos_formatados = [{"nome": n} for n in novos]
            if not any(c['nome'] == "Voto Nulo" for c in novos_formatados):
                novos_formatados.append({"nome": "Voto Nulo"})
            config['candidatos'] = novos_formatados
            votos = {n['nome']: 0 for n in novos_formatados}
            config['votaram'] = 0

    # Resetar votos
    if dados.get('reset_votos'):
        votos = {c['nome']: 0 for c in config['candidatos']}
        config['votaram'] = 0

    # Salva arquivos
    with open(ARQ_VOTOS, 'w', encoding='utf-8') as f:
        json.dump(votos, f, indent=4, ensure_ascii=False)
    with open(ARQ_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    return jsonify({'mensagem': 'Configurações atualizadas com sucesso.'})


if __name__ == '__main__':
    inicializar_arquivos()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

