"""Seed common sizes + the 30 fabric types + 45 colors from the user's catalog.
All idempotent (get_or_create), so safe to re-run."""
from django.db import migrations


SIZES = [
    # (code, sort_order)
    ('5XS',  1), ('4XS', 2), ('3XS', 3), ('2XS', 4), ('XS', 5),
    ('S',    6), ('M',   7), ('L',   8), ('XL',  9),
    ('2XL', 10), ('3XL', 11), ('4XL', 12), ('5XL', 13),
    # Numeric (children's clothing)
    ('2',  20), ('4',  21), ('6',  22), ('8',  23), ('10', 24),
    ('12', 25), ('14', 26), ('16', 27), ('18', 28),
]


FABRIC_TYPES = [
    ('Cotton 100%',     'Natural soft fabric, sweat-absorbent, comfortable, used for underwear, pajamas, and t-shirts'),
    ('Egyptian Cotton', 'Long-staple cotton, luxurious, very soft and durable, used in premium clothing and bedding'),
    ('Combed Cotton',   'Cotton combed to remove short fibers, softer and stronger than regular cotton'),
    ('Pique',           'Cotton woven with raised pattern, used for polo shirts and summer wear'),
    ('Jersey',          'Light stretchy cotton knit, used for t-shirts and pajamas'),
    ('Interlock',       'Thick durable cotton knit, double-faced, used for pajamas and underwear'),
    ('French Terry',    'Cotton with smooth face and looped back, used for sportswear and hoodies'),
    ('Fleece',          'Soft warm fabric, lightweight, used for winter clothing and pajamas'),
    ('Cotton Flannel',  'Winter cotton fabric, brushed inside, warm and comfortable'),
    ('Satin',           "Glossy smooth fabric, used for women's clothing and luxury nightgowns"),
    ('Silk',            'Luxurious soft shiny fabric, lightweight and comfortable, used for premium clothing'),
    ('Chiffon',         "Light transparent fabric, used for dresses and women's clothing"),
    ('Crepe',           'Crinkled textured fabric, flowing, used for dresses and blouses'),
    ('Viscose',         'Semi-synthetic fiber from cellulose, soft and flowing, economic silk alternative'),
    ('Polyester',       'Durable synthetic fibers, wrinkle-resistant, easy to wash'),
    ('Microfiber',      'Very fine synthetic fibers, soft and light, used for sportswear and home textiles'),
    ('Spandex (Lycra)', 'Highly elastic fibers, added to other fabrics for stretch'),
    ('Linen',           'Natural fabric from flax plant, cool and comfortable in summer, wrinkles easily'),
    ('Denim',           'Thick durable cotton fabric, used for jeans and jackets'),
    ('Gabardine',       'Durable diagonal-weave fabric, used for suits and formal pants'),
    ('Wool',            'Natural warm fibers, used for winter clothing and suits'),
    ('Cashmere',        'Very soft luxurious wool, light and warm'),
    ('Acrylic',         'Synthetic fibers similar to wool, more affordable and easy-care'),
    ('Nylon',           'Strong durable synthetic fibers, used for sportswear and bags'),
    ('Tulle',           'Light mesh fabric, used for wedding dresses and decoration'),
    ('Lace',            'Decorative patterned fabric, used for lingerie and dresses'),
    ('Velvet',          'Fabric with short dense pile, luxurious, used for clothing and upholstery'),
    ('Taffeta',         'Glossy crisp fabric, used for formal dresses'),
    ('Muslin',          'Light transparent cotton fabric, used for summer clothing'),
    ('Bamboo',          'Fibers from bamboo plant, soft and antibacterial, eco-friendly'),
]


COLORS = [
    # (name_en, hex, rgb, hsl)
    ('White',       '#FFFFFF', '255,255,255', '0,0%,100%'),
    ('Black',       '#000000', '0,0,0',       '0,0%,0%'),
    ('Light Gray',  '#D3D3D3', '211,211,211', '0,0%,83%'),
    ('Gray',        '#808080', '128,128,128', '0,0%,50%'),
    ('Dark Gray',   '#404040', '64,64,64',    '0,0%,25%'),
    ('Beige',       '#F5F5DC', '245,245,220', '60,56%,91%'),
    ('Cream',       '#FFFDD0', '255,253,208', '57,100%,91%'),
    ('Ivory',       '#FFFFF0', '255,255,240', '60,100%,97%'),
    ('Light Brown', '#A0522D', '160,82,45',   '19,56%,40%'),
    ('Brown',       '#8B4513', '139,69,19',   '25,76%,31%'),
    ('Dark Brown',  '#5C4033', '92,64,51',    '19,29%,28%'),
    ('Coffee',      '#6F4E37', '111,78,55',   '25,34%,33%'),
    ('Red',         '#FF0000', '255,0,0',     '0,100%,50%'),
    ('Dark Red',    '#8B0000', '139,0,0',     '0,100%,27%'),
    ('Maroon',      '#800000', '128,0,0',     '0,100%,25%'),
    ('Burgundy',    '#800020', '128,0,32',    '345,100%,25%'),
    ('Light Pink',  '#FFB6C1', '255,182,193', '351,100%,86%'),
    ('Pink',        '#FFC0CB', '255,192,203', '350,100%,88%'),
    ('Hot Pink',    '#FF69B4', '255,105,180', '330,100%,71%'),
    ('Fuchsia',     '#FF00FF', '255,0,255',   '300,100%,50%'),
    ('Orange',      '#FFA500', '255,165,0',   '39,100%,50%'),
    ('Dark Orange', '#FF8C00', '255,140,0',   '33,100%,50%'),
    ('Peach',       '#FFDAB9', '255,218,185', '28,100%,86%'),
    ('Coral',       '#FF7F50', '255,127,80',  '16,100%,66%'),
    ('Yellow',      '#FFFF00', '255,255,0',   '60,100%,50%'),
    ('Light Yellow','#FFFFE0', '255,255,224', '60,100%,94%'),
    ('Gold',        '#FFD700', '255,215,0',   '51,100%,50%'),
    ('Mustard',     '#FFDB58', '255,219,88',  '50,100%,67%'),
    ('Light Green', '#90EE90', '144,238,144', '120,73%,75%'),
    ('Green',       '#008000', '0,128,0',     '120,100%,25%'),
    ('Dark Green',  '#006400', '0,100,0',     '120,100%,20%'),
    ('Olive',       '#808000', '128,128,0',   '60,100%,25%'),
    ('Turquoise',   '#40E0D0', '64,224,208',  '174,72%,56%'),
    ('Mint',        '#98FF98', '152,255,152', '120,100%,80%'),
    ('Sky Blue',    '#87CEEB', '135,206,235', '197,71%,73%'),
    ('Light Blue',  '#ADD8E6', '173,216,230', '195,53%,79%'),
    ('Blue',        '#0000FF', '0,0,255',     '240,100%,50%'),
    ('Dark Blue',   '#00008B', '0,0,139',     '240,100%,27%'),
    ('Navy',        '#000080', '0,0,128',     '240,100%,25%'),
    ('Teal',        '#008080', '0,128,128',   '180,100%,25%'),
    ('Lavender',    '#E6E6FA', '230,230,250', '240,67%,94%'),
    ('Purple',      '#800080', '128,0,128',   '300,100%,25%'),
    ('Violet',      '#EE82EE', '238,130,238', '300,76%,72%'),
    ('Indigo',      '#4B0082', '75,0,130',    '275,100%,25%'),
    ('Silver',      '#C0C0C0', '192,192,192', '0,0%,75%'),
]


def forward(apps, schema_editor):
    Size       = apps.get_model('manufacturing', 'Size')
    FabricType = apps.get_model('manufacturing', 'FabricType')
    FabricColor = apps.get_model('manufacturing', 'FabricColor')

    # Sizes
    for code, order in SIZES:
        Size.objects.get_or_create(code=code, defaults={'sort_order': order, 'active': True})

    # Fabric types — code FAB-001 .. FAB-030, name_en + description
    for i, (name_en, desc) in enumerate(FABRIC_TYPES, start=1):
        code = f'FAB-{i:03d}'
        FabricType.objects.get_or_create(
            code=code,
            defaults={
                'name_ar': name_en,    # English by default; user can translate later
                'name_en': name_en,
                'description': desc,
                'active': True,
            },
        )

    # Colors — code CLR-001 .. CLR-045
    for i, (name_en, hex_code, rgb, hsl) in enumerate(COLORS, start=1):
        code = f'CLR-{i:03d}'
        FabricColor.objects.get_or_create(
            code=code,
            defaults={
                'name_ar': name_en,
                'name_en': name_en,
                'hex_code': hex_code,
                'rgb': rgb,
                'hsl': hsl,
                'is_raw': False,
                'active': True,
            },
        )


def backward(apps, schema_editor):
    Size       = apps.get_model('manufacturing', 'Size')
    FabricType = apps.get_model('manufacturing', 'FabricType')
    FabricColor = apps.get_model('manufacturing', 'FabricColor')
    Size.objects.filter(code__in=[c for c, _ in SIZES]).delete()
    FabricType.objects.filter(code__startswith='FAB-').delete()
    FabricColor.objects.filter(code__startswith='CLR-').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('manufacturing', '0013_size_alter_productionsize_options_and_more'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
