"""Response contracts for Gemini. Local evidence checks remain authoritative."""
ANSWER_SCHEMA = {
    'type': 'object',
    'properties': {
        'status': {'type': 'string', 'enum': ['answered', 'insufficient_evidence']},
        'claims': {'type': 'array', 'maxItems': 5, 'items': {
            'type': 'object',
            'properties': {
                'text': {'type': 'string'},
                'citation_ids': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}},
            },
            'required': ['text', 'citation_ids'],
            'additionalProperties': False,
        }},
    },
    'required': ['status', 'claims'],
    'additionalProperties': False,
}

VERIFY_SCHEMA = {
    'type': 'object',
    'properties': {
        'answers_question': {'type': 'boolean'},
        'checks': {'type': 'array', 'maxItems': 5, 'items': {
            'type': 'object',
            'properties': {
                'index': {'type': 'integer', 'minimum': 0, 'maximum': 4},
                'supported': {'type': 'boolean'},
                'evidence': {'type': 'array', 'items': {
                    'type': 'object',
                    'properties': {'id': {'type': 'string'}, 'quote': {'type': 'string'}},
                    'required': ['id', 'quote'],
                    'additionalProperties': False,
                }},
            },
            'required': ['index', 'supported', 'evidence'],
            'additionalProperties': False,
        }},
    },
    'required': ['answers_question', 'checks'],
    'additionalProperties': False,
}
