import bpy, math, os
from mathutils import Vector

OUT = r"D:\program\Zhihu\cat_model.blend"
RENDER = r"D:\program\Zhihu\cat_model_preview.png"
GLB = r"D:\program\Zhihu\cat_model.glb"

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    pass

def mat(name, color, rough=0.55, metallic=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bs = m.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value = (*color, 1)
    bs.inputs['Roughness'].default_value = rough
    bs.inputs['Metallic'].default_value = metallic
    return m

WHITE = mat('Warm White Fur', (0.96, 0.90, 0.82), 0.72)
PINK = mat('Blush Pink Fabric', (0.82, 0.40, 0.40), 0.88)
PINK_LIGHT = mat('Soft Pink Trim', (0.98, 0.70, 0.70), 0.82)
BLACK = mat('Glossy Black', (0.008, 0.006, 0.005), 0.2)
BROWN = mat('Mouth Brown', (0.22, 0.05, 0.03), 0.4)
BLUE = mat('Tear Blue', (0.18, 0.55, 0.95), 0.3)
FLOOR = mat('Studio Floor', (0.035, 0.04, 0.05), 0.65)

def smooth(obj):
    if obj.type == 'MESH':
        for p in obj.data.polygons: p.use_smooth = True
    return obj

def uv(name, loc, scale, material, seg=48, rings=32):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=rings, location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(material); return smooth(o)

def cube(name, loc, scale, material, bevel=0.12, rot=(0,0,0)):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o=bpy.context.object; o.name=name; o.scale=scale; bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        b=o.modifiers.new('Soft sewn edges','BEVEL'); b.width=bevel; b.segments=4
    o.data.materials.append(material); return o

def cone(name, loc, r1, r2, depth, material, rot=(0,0,0), verts=64):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=depth, location=loc, rotation=rot)
    o=bpy.context.object; o.name=name; o.data.materials.append(material); return smooth(o)

def torus(name, loc, major, minor, material, rot=(0,0,0)):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, major_segments=64, minor_segments=20, location=loc, rotation=rot)
    o=bpy.context.object; o.name=name; o.data.materials.append(material); return smooth(o)

def cylinder_between(name, a, b, radius, material):
    a,b=Vector(a),Vector(b); d=b-a; mid=(a+b)/2
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=radius, depth=d.length, location=mid)
    o=bpy.context.object; o.name=name; o.data.materials.append(material)
    o.rotation_mode='QUATERNION'; o.rotation_quaternion=d.to_track_quat('Z','Y'); return smooth(o)

# Character core
uv('Body_Fur', (0,0,1.72), (0.78,0.48,1.02), WHITE)
uv('Head_Fur', (0,-0.02,2.78), (0.86,0.72,0.78), WHITE)

# Ears, inner ear patches
cone('Ear_L', (-0.53,0.0,3.42), 0.36, 0.05, 0.72, WHITE, rot=(0.0,-0.18,-0.10))
cone('Ear_R', (0.53,0.0,3.42), 0.36, 0.05, 0.72, WHITE, rot=(0.0,0.18,0.10))
uv('InnerEar_L', (-0.53,-0.07,3.46), (0.18,0.07,0.28), PINK_LIGHT)
uv('InnerEar_R', (0.53,-0.07,3.46), (0.18,0.07,0.28), PINK_LIGHT)

# Face
uv('Muzzle_L', (-0.18,-0.67,2.58), (0.29,0.16,0.23), WHITE)
uv('Muzzle_R', (0.18,-0.67,2.58), (0.29,0.16,0.23), WHITE)
uv('Nose', (0,-0.83,2.63), (0.17,0.10,0.13), BLACK)
uv('Eye_L', (-0.30,-0.67,2.91), (0.095,0.06,0.13), BLACK)
uv('Eye_R', (0.30,-0.67,2.91), (0.095,0.06,0.13), BLACK)
uv('EyeHighlight_L', (-0.325,-0.724,2.955), (0.025,0.018,0.035), WHITE)
uv('EyeHighlight_R', (0.275,-0.724,2.955), (0.025,0.018,0.035), WHITE)
uv('Cheek_L', (-0.53,-0.64,2.54), (0.13,0.04,0.10), PINK_LIGHT)
uv('Cheek_R', (0.53,-0.64,2.54), (0.13,0.04,0.10), PINK_LIGHT)

# Bow on right side of head
uv('Bow_L', (0.46,-0.57,3.20), (0.25,0.08,0.16), PINK_LIGHT)
uv('Bow_R', (0.74,-0.52,3.22), (0.22,0.08,0.17), PINK_LIGHT)
uv('Bow_Knot', (0.60,-0.66,3.20), (0.10,0.07,0.10), PINK_LIGHT)

# Collar, vest and skirt
torus('Plush_Collar', (0,-0.01,2.30), 0.62, 0.16, WHITE)
cube('Vest_Left', (-0.34,-0.49,1.85), (0.34,0.08,0.52), PINK, bevel=0.10, rot=(0.0,0.05,0.02))
cube('Vest_Right', (0.34,-0.49,1.85), (0.34,0.08,0.52), PINK, bevel=0.10, rot=(0.0,-0.05,-0.02))
cube('Vest_Trim', (0,-0.58,1.86), (0.07,0.045,0.53), PINK_LIGHT, bevel=0.03)
cone('Skirt', (0,-0.01,1.13), 1.00, 0.78, 0.46, PINK_LIGHT)
torus('Skirt_Waist', (0,0,1.36), 0.79, 0.08, PINK)

# Pockets and buttons
for sx in (-1,1):
    x=0.34*sx
    cube('Pocket_'+('L' if sx<0 else 'R'), (x,-0.61,1.88), (0.19,0.035,0.17), PINK_LIGHT, bevel=0.045)
    uv('PocketButton_'+('L' if sx<0 else 'R'), (x,-0.66,1.98), (0.035,0.02,0.035), WHITE)

# Arms and hands
for sx in (-1,1):
    x=0.88*sx
    uv('Arm_'+('L' if sx<0 else 'R'), (x,-0.03,1.84), (0.24,0.25,0.66), WHITE)
    uv('Hand_'+('L' if sx<0 else 'R'), (x,-0.18,1.28), (0.25,0.24,0.28), WHITE)

# Legs, feet and toe hints
for sx in (-1,1):
    x=0.36*sx
    uv('Leg_'+('L' if sx<0 else 'R'), (x,0.0,0.66), (0.28,0.30,0.56), WHITE)
    uv('Foot_'+('L' if sx<0 else 'R'), (x,-0.14,0.22), (0.34,0.40,0.22), WHITE)
    for tx in (-0.10,0,0.10):
        uv('Toe', (x+tx*0.9,-0.49,0.22), (0.045,0.025,0.06), PINK_LIGHT, seg=24, rings=16)

# Tail behind the right side, built as a tapered curved chain
tail_pts=[(0.62,0.37,1.05),(1.02,0.62,0.92),(1.34,0.68,1.18),(1.47,0.58,1.50)]
for i in range(len(tail_pts)-1): cylinder_between('Tail_%02d'%i,tail_pts[i],tail_pts[i+1],0.23-0.025*i,WHITE)
uv('TailTip', tail_pts[-1], (0.20,0.20,0.25), WHITE)

# Small mouth line and tongue for friendly expression
uv('Mouth', (0,-0.84,2.47), (0.075,0.018,0.025), BLACK, seg=24, rings=16)
uv('Tongue', (0,-0.86,2.40), (0.08,0.025,0.055), BROWN, seg=24, rings=16)

# Ground and backdrop
bpy.ops.mesh.primitive_plane_add(size=30, location=(0,0,0))
floor=bpy.context.object; floor.name='Ground'; floor.data.materials.append(FLOOR)

# Lighting
bpy.ops.object.light_add(type='AREA', location=(3.8,-5.5,6.0)); key=bpy.context.object; key.name='Key'; key.data.energy=900; key.data.shape='DISK'; key.data.size=4.0
key.rotation_euler=(math.radians(28),0,math.radians(35))
bpy.ops.object.light_add(type='AREA', location=(-4.0,-3.0,3.5)); fill=bpy.context.object; fill.data.energy=550; fill.data.size=3.0
fill.rotation_euler=(math.radians(65),0,math.radians(-55))
bpy.ops.object.light_add(type='AREA', location=(0,2.5,4.8)); rim=bpy.context.object; rim.data.energy=700; rim.data.size=3.0
rim.rotation_euler=(math.radians(-30),0,math.radians(180))

def look_at(obj, target):
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()

bpy.ops.object.camera_add(location=(0,-9.2,2.15)); cam=bpy.context.object; cam.name='Camera_Front'; cam.data.lens=58; look_at(cam,(0,0,1.75)); bpy.context.scene.camera=cam
bpy.ops.object.camera_add(location=(5.8,-7.2,3.0)); cam3=bpy.context.object; cam3.name='Camera_ThreeQuarter'; cam3.data.lens=60; look_at(cam3,(0,0,1.75))
bpy.ops.object.camera_add(location=(0,8.8,2.4)); camb=bpy.context.object; camb.name='Camera_Back'; camb.data.lens=58; look_at(camb,(0,0,1.7))

scene=bpy.context.scene
scene.render.engine='BLENDER_WORKBENCH'
scene.display.shading.light='STUDIO'
scene.display.shading.studio_light='paint.sl'
scene.display.shading.color_type='MATERIAL'
scene.render.resolution_x=700; scene.render.resolution_y=700; scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'; scene.render.filepath=RENDER
scene.world.color=(0.012,0.012,0.018)
scene.render.film_transparent=False
scene.view_settings.look='AgX - Medium High Contrast'

# Organize metadata
for o in bpy.context.scene.objects:
    if o.type=='MESH': o['asset_role']='stylized_cat_character'; o['source_reference']='codex-clipboard-baa023b4-46c4-4216-aed5-0b7d739b2216.png'

# Save, render, export
bpy.ops.wm.save_as_mainfile(filepath=OUT)
scene.camera=cam
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
try:
    bpy.ops.export_scene.gltf(filepath=GLB, export_format='GLB', use_selection=False)
except Exception as e:
    print('GLB export skipped:', e)
print('DONE', OUT, RENDER, GLB)
