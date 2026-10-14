"""The tank Iroha rides - a part, not an eighth pet. Lives in other_models/.

Blue Archive exports her vehicle separately from her, and Iroha.glb's copy of it
is the broken one: the hull material CH0156_Tank_01 carries no baseColorTexture
at all, and its UVs are a mangled merge (though the 400 out-of-range vertices
turn out to be orphans no triangle references). other_models/ holds the same tank
rigged out on its own, with the real 512x512 hull texture in it - iroha.py
borrows it, and that is the only reason this file is needed at all.

It is kept out of model/ so it does not become a character: its bones are the
tank's, not a student's, so it has no Cafe_Idle or any of the other clips a
character needs, and without `pet = False` you would get a motionless tank
standing on the taskbar. `pet = False` still matters if you point --model at
this folder on purpose.
"""

PROFILE = dict(pet=False)