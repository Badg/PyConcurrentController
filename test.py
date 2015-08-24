from IPython import embed
import aimms30
import copy
a = aimms30.utils.SliceDeque([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15])
b = copy.copy(a)

embed()