import numpy as np
import h5py
from sacred import Experiment
from PIL import Image
from scipy.ndimage import rotate
from time import ctime

Image.MAX_IMAGE_PIXELS=1e10
ex = Experiment()

@ex.config
def config():
    params = {
        'ws': 100,
        'slope_dist': 640,
        'angle_step': 15,
        'image_path': '/home/ainaz/Projects/Landslides/image_data/Veneto_NEW/data/Veneto/',
        'data_path': '../image_data/n_dataset_oldgt.h5',
        'feature_num': 94,
        'save_to': '../image_data/rot_landslide_.h5',
        'region': 'Veneto',
        'pad': 64,
        'write_slope_files': False,
    }

def find_maxws(params):
    return int(params['ws']*np.sqrt(2))+1

def normalize(data):
    data[data<0]=0
    data[data>180]=0
    mean = np.mean(data)
    std = np.std(data)
    data = (data-mean)/std
    return data

def load_slopeFiles(params, data_flag, _log):
    path = ('/').join(params['save_to'].split('/')[:-1])+'/{}_rotslopes.h5'
    write = params['write_slope_files']
    if write:
        slope = np.array(Image.open(params['image_path']+'slope.tif'))
        slope = normalize(slope)
        _log.info('{}: slope is loaded and normalized'.format(ctime()))
        (h, w) = slope.shape
        if data_flag == 'train':
            data = slope[:, 0:2*(w//3)]
        else:
            data = slope[:, 2*(w//3):]
        f = h5py.File(path, 'w')
        for angle in np.arange(0, 360, params['angle_step']):
            n_shape = find_nshape(deg2rad(angle), data.shape)
            f.create_dataset(str(angle), n_shape, dtype='f', compression='lzf')
            f[str(angle)][:, :] = rotate(data, angle, reshape=True, mode='reflect')
            _log.info('{}: writing slope with angle {}'.format(ctime, str(angle)))
    else:
        f = h5py.File(path, 'r')
        _log.info('{}: slope datasets are read'.format(ctime()))
    return f

def initialize_dataset(f, shape, data_flag, params):
    (h, w) = shape
    f.create_dataset(
        '{}/{}/data/'.format(params['region'], data_flag),
        (params['feature_num'], h, w),
        compression='lzf'
    )
    f.create_dataset('{}/{}/gt'.format(params['region'], data_flag), (1, h, w), compression='lzf')
    
    zero_data = np.zeros((h, w))
    for idx in range(params['feature_num']):
        f['{}/{}/data'.format(params['region'], data_flag)][idx, :, :] = zero_data
    return f

def deg2rad(theta):
    return (np.pi*theta)/180

def find_nshape(theta, prev_shape):
    (h, w) = prev_shape
    nh = np.cos(theta)*h + np.sin(theta)*w
    nw = np.sin(theta)*h + np.cos(theta)*w
    return (nh, nw)

def transform_mat(theta, scale, c_coord, prev_shape):
    theta_rad = deg2rad(theta)
    (nh, nw) = find_nshape(theta_rad, prev_shape)
    alpha = scale * np.cos(theta_rad)
    beta = scale * np.sin(theta_rad)
    mat = np.array(
        [[alpha, beta, (1-alpha)*c_coord[1]-beta*c_coord[0]+(nw/2-c_coord[1])],
        [-beta, alpha, beta*c_coord[1]+(1-alpha)*c_coord[0]+(nh/2-c_coord[0])]]
    )
    return mat

def find_rotated_coord(point, theta, scale, c_coord, prev_shape):
    M = transform_mat(theta, scale, c_coord, prev_shape)
    v = [point[1], point[0], 1]
    v_transformed = np.dot(M, v)
    return (v_transformed[1], v_transformed[0]) # swap x, y ro correspond to row, col

def my_rotate(params, angle, target_shape, index, flag):
    f = h5py.File(params['data_path'], 'r')
    (row, col) = index
    (nh, nw) = find_nshape(deg2rad(angle), (params['ws'], params['ws']))
    rot_data = np.zeros((params['feature_num'], target_shape[0], target_shape[1]))
    dif_h = target_shape[0]-nh
    dif_w = target_shape[1]-nw
    for channel in range(params['feature_num']):
        data = f[params['region']][flag]['data'][
            channel,
            row*params['ws']:(row+1)*params['ws'],
            col*params['ws']:(col+1)*params['ws']
        ]
        rot_data[channel, :, :] = np.pad(
            rotate(data, angle, reshape=True, mode='reflect'),
            ((dif_h//2, dif_h-dif_h//2), (dif_w//2, dif_w-dif_w//2)),
            mode='edge'
        )
    gt = f[params['region']][flag]['gt'][
            0,
            row*params['ws']:(row+1)*params['ws'],
            col*params['ws']:(col+1)*params['ws']
    ]
    rot_gt = np.pad(
        rotate(gt, angle, reshape=True, mode='reflect'),
        ((dif_h//2, dif_h-dif_h//2), (dif_w//2, dif_w-dif_w//2)),
        mode='edge'
    )
    return rot_data, rot_gt

@ex.automain
def find_angles(params, _log):
    f = h5py.File(params['save_to'], 'w')
    _log.info('{}: prepared the dataset for writing'.format(ctime()))
    for flag in ['train', 'test']:
        s_f = load_slopeFiles(params, flag, _log)
        (h, w) = s_f['0'].shape
        hnum, wnum = h//params['ws'], w//params['ws']
        rot_ws = find_maxws(params)
        n_h, n_w = rot_ws*hnum, rot_ws*wnum
        _log.info('{}: new shape -> ({}, {}), old shape -> ({}, {}), maximum ws -> {}'.format(ctime(), n_h, n_w, h, w, rot_ws))
        f = initialize_dataset(f, (n_h, n_w), flag, params)
        _log.info('{}: {} dataset is initialized with zeros'.format(ctime(), flag))
        for row in range(hnum):   
            for col in range(wnum):
                pt_value = s_f[0][
                    row*params['ws']:(row+1)*params['ws'],
                    col*params['ws']:(col+1)*params['ws']
                    ][
                        params['ws']//2, params['ws']//2
                    ]
                pt_coord = (row*params['ws']+(params['ws']//2), col*params['ws']+(params['ws']//2))
                center_coord = (h//2, w//2)
                best_angle = 0
                angle = 0
                for angle in np.arange(params['angle_step'], 360, params['angle_step']):
                    rot_coord = find_rotated_coord(pt_coord, angle, 1, center_coord, (h, w))
                    rot_value = s_f[str(angle)][rot_coord[0], rot_coord[1]]
                    if rot_value != pt_value:
                        print('the values for the rotated image and the original image are not matching.')
                        raise ValueError
                    d = params['slope_dist']
                    dist_value = s_f[str(angle)][rot_coord[0]-d, rot_coord[1]]
                    if dist_value > pt_value:
                        best_angle = angle
                        break
                _log.info('{}: best angle = {} with slope = {} > {}'.format(ctime(), str(best_angle), str(dist_value), str(pt_value)))
                rot_data, rot_gt = my_rotate(params, best_angle, (rot_ws, rot_ws), (row, col), flag)
                f[params['region']][flag]['data'][
                    :,
                    row*rot_ws:(row+1)*rot_ws,
                    col*rot_ws:(col+1)*rot_ws
                ] = rot_data
                f[params['region']][flag]['gt'][
                    :,
                    row*rot_ws:(row+1)*rot_ws,
                    col*rot_ws:(col+1)*rot_ws
                ] = rot_gt
                _log.info('{}: writing patch [({}, {})]/[({}, {})] in {}'.format(
                    ctime(),
                    str(row),
                    str(col),
                    str(hnum),
                    str(wnum),
                    flag
                ))
    _log.info('{}: dataset is written. closing the file ...'.format(ctime()))
    f.close()