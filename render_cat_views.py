import bpy, os
blend=r'D:\program\Zhihu\cat_model.blend'
bpy.ops.wm.open_mainfile(filepath=blend)
scene=bpy.context.scene
for cam_name, fn in [('Camera_Front','cat_front.png'),('Camera_ThreeQuarter','cat_3q.png'),('Camera_Back','cat_back.png')]:
    scene.camera=bpy.data.objects.get(cam_name)
    scene.render.filepath=os.path.join(r'D:\program\Zhihu',fn)
    bpy.ops.render.render(write_still=True)
print('VIEW_DONE')
