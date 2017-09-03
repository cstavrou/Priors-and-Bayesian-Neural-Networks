# =======================================================================================================
# Using the MNIST dataset
# =======================================================================================================


# ============
# Description
# ============
# Performs HMC inference on a 2 hidden layer Bayesian NN

#
# Inference performed sequentially, initial HMC run to learn the initial parameters
# Average the samples from phase 1 of the learning and run inference again to 
# collect samples

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import tensorflow as tf
from tensorflow.examples.tutorials.mnist import input_data
from edward.models import Categorical, Normal, Laplace, Empirical, StudentT
import edward as ed
from pandas.plotting import autocorrelation_plot
from statsmodels.graphics.tsaplots import plot_pacf, plot_acf
from statsmodels.tsa.stattools import acf
import pandas as pd
import sys
import timeit
import random
import cv2
import os
from sklearn.metrics import confusion_matrix

# Load the MNIST data
mnist = input_data.read_data_sets("MNIST_data/", one_hot=True)

# Load the test images.
X_test = mnist.test.images
# TensorFlow method gives the label data in a one hot vetor format. We convert that into a single label.
Y_test = np.argmax(mnist.test.labels,axis=1)

# Halves the size of the images
def resize(images):
	im = np.reshape(images, [-1,28,28])
	n = np.shape(im)[0]
	reduced_im = np.zeros([n, 14, 14])
	for ind in range(n):
		reduced_im[ind,:,:] = cv2.resize(im[ind,:,:], (14, 14))
	grey_im = (0.1 < reduced_im).astype('float32')
	return np.reshape(grey_im, [-1, 14*14])

D = int(14**2)

ed.set_seed(314159)
np.random.seed(seed=314159)
N = int(sys.argv[1])   # number of images in a minibatch.
n_hidden = int(sys.argv[2])

K = np.shape(mnist.test.labels)[1]      # number of classes.
n_samp = int(sys.argv[5])               # number of samples for HMC.
leap_size = float(sys.argv[6])
step_no = int(sys.argv[7])
nburn = int(sys.argv[8])
std = float(sys.argv[9])
n_iter_learn = int(sys.argv[10])        # Number of iterations of learning
if str(sys.argv[4]) == 'T':
	df = float(sys.argv[11])


def nn(x, W_0, b_0, W_1, b_1, W_2, b_2):
    h1 = tf.nn.softplus(tf.matmul(x, W_0) + b_0)
    h2 = tf.nn.softplus(tf.matmul(h1, W_1) + b_1)
    out = tf.matmul(h2, W_2) + b_2
    return out

def pred_nn(x, W_0, b_0, W_1, b_1, W_2, b_2):
    h1 = tf.nn.softplus(tf.matmul(x, W_0) + b_0)
    h2 = tf.nn.softplus(tf.matmul(h1, W_1) + b_1)
    o = tf.nn.softmax(tf.matmul(h2, W_2) + b_2)
    return tf.reshape(tf.argmax(o, 1), [-1])

def mean_acc(Y_true, Y_hat):
    acc = Y_true == Y_hat
    return np.mean(acc)  

def probs_nn(x, W_0, b_0, W_1, b_1, W_2, b_2):
    h1 = tf.nn.softplus(tf.matmul(x, W_0) + b_0)
    h2 = tf.nn.softplus(tf.matmul(h1, W_1) + b_1)
    out_probs = tf.nn.softmax(tf.matmul(h2, W_2) + b_2)
    return tf.reshape(out_probs, [-1, K])

# Build predictive graph

def pred_graph():
	x_pred = tf.placeholder(tf.float32, [None, None])
	ww0 = tf.placeholder(tf.float32, [None, None])
	ww1 = tf.placeholder(tf.float32, [None, None])
	ww2 = tf.placeholder(tf.float32, [None, None])
	bb0 = tf.placeholder(tf.float32, [None])
	bb1 = tf.placeholder(tf.float32, [None])
	bb2 = tf.placeholder(tf.float32, [None])
	y_pred = pred_nn(x_pred, ww0, bb0, ww1, bb1, ww2, bb2)
	return x_pred, ww0, ww1, ww2, bb0, bb1, bb2, y_pred

def pred_graph_2():
	x_in = tf.placeholder(tf.float32, [None, None])
	w0_fin = tf.placeholder(tf.float32, [None, None])
	w1_fin = tf.placeholder(tf.float32, [None, None])
	w2_fin = tf.placeholder(tf.float32, [None, None])
	b0_fin = tf.placeholder(tf.float32, [None])
	b1_fin = tf.placeholder(tf.float32, [None])
	b2_fin = tf.placeholder(tf.float32, [None])
	prob_out = probs_nn(x_in, w0_fin, b0_fin, w1_fin, b1_fin, w2_fin, b2_fin)
	return x_in, w0_fin, b0_fin, w1_fin, b1_fin, w2_fin, b2_fin, prob_out

# Inference graph (initial)
def ed_graph_init():
	# Priors
	if str(sys.argv[4]) == 'laplace':
		W_0 = Laplace(loc=tf.zeros([D, n_hidden]), scale=(std**2/D)*tf.ones([D, n_hidden]))
		W_1 = Laplace(loc=tf.zeros([n_hidden, n_hidden]), scale=(std**2/n_hidden)*tf.ones([n_hidden, n_hidden]))
		W_2 = Laplace(loc=tf.zeros([n_hidden, K]), scale=(std**2/n_hidden)*tf.ones([n_hidden, K]))
		b_0 = Laplace(loc=tf.zeros(n_hidden), scale=(std**2/D)*tf.ones(n_hidden))
		b_1 = Laplace(loc=tf.zeros(n_hidden), scale=(std**2/n_hidden)*tf.ones(n_hidden))
		b_2 = Laplace(loc=tf.zeros(K), scale=(std**2/n_hidden)*tf.ones(K))

	if str(sys.argv[4]) == 'normal':
		W_0 = Normal(loc=tf.zeros([D, n_hidden]), scale=std*D**-.5*tf.ones([D, n_hidden]))
		W_1 = Normal(loc=tf.zeros([n_hidden, K]), scale=std*n_hidden**-.5*tf.ones([n_hidden, K]))
		W_2 = Normal(loc=tf.zeros([n_hidden, K]), scale=std*n_hidden**-.5*tf.ones([n_hidden, K]))
		b_0 = Normal(loc=tf.zeros(n_hidden), scale=std*D**-.5*tf.ones(n_hidden))
		b_1 = Normal(loc=tf.zeros(n_hidden), scale=10*n_hidden**(-.5)*tf.ones(n_hidden))
		b_2 = Normal(loc=tf.zeros(K), scale=10*n_hidden**(-.5)*tf.ones(K))

	if str(sys.argv[4]) == 'T':
		W_0 = StudentT(df=df*tf.ones([D, n_hidden]), loc=tf.zeros([D, n_hidden]), scale=(std**2/D)*tf.ones([D, n_hidden]))
		W_1 = StudentT(df=df*tf.ones([n_hidden, n_hidden]), loc=tf.zeros([n_hidden, n_hidden]), scale=(std**2/n_hidden)*tf.ones([n_hidden, n_hidden]))
		W_2 = StudentT(df=df*tf.ones([n_hidden, K]), loc=tf.zeros([n_hidden, K]), scale=(std**2/n_hidden)*tf.ones([n_hidden, K]))
		b_0 = StudentT(df=df*tf.ones([n_hidden]), loc=tf.zeros(n_hidden), scale=(std**2/D)*tf.ones(n_hidden))
		b_1 = StudentT(df=df*tf.ones([n_hidden]), loc=tf.zeros(n_hidden), scale=(std**2/n_hidden)*tf.ones(n_hidden))
		b_2 = StudentT(df=df*tf.ones([K]), loc=tf.zeros(K), scale=(std**2/n_hidden)*tf.ones(K))

	x = tf.placeholder(tf.float32, [None, None])
	# Categorical likelihood
	y = Categorical(logits=nn(x, W_0, b_0, W_1, b_1, W_2, b_2))
	# We use a placeholder for the labels in anticipation of the traning data.
	y_ph = tf.placeholder(tf.int32, [N])

	# Posteriors
	if str(sys.argv[4]) == 'normal':
		qW_0 = Empirical(params=tf.Variable(tf.random_normal([n_samp, D, n_hidden], stddev=std*(D**-.5))))
		qW_1 = Empirical(params=tf.Variable(tf.random_normal([n_samp, n_hidden, n_hidden], stddev=std*(n_hidden**-.5))))
		qW_2 = Empirical(params=tf.Variable(tf.random_normal([n_samp, n_hidden, K], stddev=std*(n_hidden**-.5))))
		qb_0 = Empirical(params=tf.Variable(tf.random_normal([n_samp, n_hidden], stddev=std*(D**-.5))))
		qb_1 = Empirical(params=tf.Variable(tf.random_normal([n_samp, n_hidden], stddev=std*(n_hidden**-.5))))
		qb_2 = Empirical(params=tf.Variable(tf.random_normal([n_samp, K], stddev=std*(n_hidden**-.5))))

	if str(sys.argv[4]) == 'laplace' or str(sys.argv[4]) == 'T':
		# Use a placeholder otherwise cannot assign a tensor > 2GB
		p0 = tf.placeholder(tf.float32, [n_samp, D, n_hidden])
		p1 = tf.placeholder(tf.float32, [n_samp, n_hidden, n_hidden])
		p2 = tf.placeholder(tf.float32, [n_samp, n_hidden, K])
		pp0 = tf.placeholder(tf.float32, [n_samp, n_hidden])
		pp1 = tf.placeholder(tf.float32, [n_samp, n_hidden])
		pp2 = tf.placeholder(tf.float32, [n_samp, K])

		w0 = tf.Variable(p0)
		w1 = tf.Variable(p1)
		w2 = tf.Variable(p2)		
		b0 = tf.Variable(pp0)		
		b1 = tf.Variable(pp1)
		b2 = tf.Variable(pp2)
		# Empirical distribution will be laplace(0,1)
		qW_0 = Empirical(params=w0)
		qW_1 = Empirical(params=w1)
		qW_2 = Empirical(params=w2)
		qb_0 = Empirical(params=b0)
		qb_1 = Empirical(params=b1)
		qb_2 = Empirical(params=b2)
	
	if str(sys.argv[3]) == 'hmc':	
		inference = ed.HMC({W_0: qW_0, b_0: qb_0, W_1: qW_1, b_1: qb_1,  W_2: qW_2, b_2: qb_2}, data={y: y_ph})
	if str(sys.argv[3]) == 'sghmc':	
		inference = ed.SGHMC({W_0: qW_0, b_0: qb_0, W_1: qW_1, b_1: qb_1,  W_2: qW_2, b_2: qb_2}, data={y: y_ph})

	# Initialse the inference variables
	if str(sys.argv[3]) == 'hmc':
		inference.initialize(step_size = leap_size, n_steps = step_no, n_print=100, 
			scale={y: float(mnist.train.num_examples) / N})
	if str(sys.argv[3]) == 'sghmc':
		inference.initialize(step_size = leap_size, friction=0.4, n_print=100, 
			scale={y: float(mnist.train.num_examples) / N})
	
	if str(sys.argv[4]) == 'laplace' or str(sys.argv[4]) == 'T':
		return ((x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, qW_0, qb_0, qW_1, qb_1, qW_2, qb_2, inference,
			p0, p1, p2, pp0, pp1, pp2, w0, w1, w2, b0, b1, b2)
	else:
		return (x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, qW_0, qb_0, qW_1, qb_1, qW_2, qb_2, inference


# Inference graph (second phase)
def ed_graph_2(disc=1):
	# Priors
	if str(sys.argv[4]) == 'laplace':
		W_0 = Laplace(loc=tf.zeros([D, n_hidden]), scale=(std**2/D)*tf.ones([D, n_hidden]))
		W_1 = Laplace(loc=tf.zeros([n_hidden, n_hidden]), scale=(std**2/n_hidden)*tf.ones([n_hidden, n_hidden]))
		W_2 = Laplace(loc=tf.zeros([n_hidden, K]), scale=(std**2/n_hidden)*tf.ones([n_hidden, K]))
		b_0 = Laplace(loc=tf.zeros(n_hidden), scale=(std**2/D)*tf.ones(n_hidden))
		b_1 = Laplace(loc=tf.zeros(n_hidden), scale=(std**2/n_hidden)*tf.ones(n_hidden))
		b_2 = Laplace(loc=tf.zeros(K), scale=(std**2/n_hidden)*tf.ones(K))

	if str(sys.argv[4]) == 'normal':
		W_0 = Normal(loc=tf.zeros([D, n_hidden]), scale=std*D**-.5*tf.ones([D, n_hidden]))
		W_1 = Normal(loc=tf.zeros([n_hidden, K]), scale=std*n_hidden**-.5*tf.ones([n_hidden, K]))
		W_2 = Normal(loc=tf.zeros([n_hidden, K]), scale=std*n_hidden**-.5*tf.ones([n_hidden, K]))
		b_0 = Normal(loc=tf.zeros(n_hidden), scale=std*D**-.5*tf.ones(n_hidden))
		b_1 = Normal(loc=tf.zeros(n_hidden), scale=10*n_hidden**(-.5)*tf.ones(n_hidden))
		b_2 = Normal(loc=tf.zeros(K), scale=10*n_hidden**(-.5)*tf.ones(K))

	if str(sys.argv[4]) == 'T':
		W_0 = StudentT(df=df*tf.ones([D, n_hidden]), loc=tf.zeros([D, n_hidden]), scale=(std**2/D)*tf.ones([D, n_hidden]))
		W_1 = StudentT(df=df*tf.ones([n_hidden, n_hidden]), loc=tf.zeros([n_hidden, n_hidden]), scale=(std**2/n_hidden)*tf.ones([n_hidden, n_hidden]))
		W_2 = StudentT(df=df*tf.ones([n_hidden, K]), loc=tf.zeros([n_hidden, K]), scale=(std**2/n_hidden)*tf.ones([n_hidden, K]))
		b_0 = StudentT(df=df*tf.ones([n_hidden]), loc=tf.zeros(n_hidden), scale=(std**2/D)*tf.ones(n_hidden))
		b_1 = StudentT(df=df*tf.ones([n_hidden]), loc=tf.zeros(n_hidden), scale=(std**2/n_hidden)*tf.ones(n_hidden))
		b_2 = StudentT(df=df*tf.ones([K]), loc=tf.zeros(K), scale=(std**2/n_hidden)*tf.ones(K))

	x = tf.placeholder(tf.float32, [None, None])
	y = Categorical(logits=nn(x, W_0, b_0, W_1, b_1, W_2, b_2))
	# We use a placeholder for the labels in anticipation of the traning data.
	y_ph = tf.placeholder(tf.int32, [N])

	# Use a placeholder for the pre-trained posteriors
	p0 = tf.placeholder(tf.float32, [n_samp, D, n_hidden])
	p1 = tf.placeholder(tf.float32, [n_samp, n_hidden, n_hidden])
	p2 = tf.placeholder(tf.float32, [n_samp, n_hidden, K])
	pp0 = tf.placeholder(tf.float32, [n_samp, n_hidden])
	pp1 = tf.placeholder(tf.float32, [n_samp, n_hidden])
	pp2 = tf.placeholder(tf.float32, [n_samp, K])

	w0 = tf.Variable(p0)
	w1 = tf.Variable(p1)
	w2 = tf.Variable(p2)		
	b0 = tf.Variable(pp0)		
	b1 = tf.Variable(pp1)
	b2 = tf.Variable(pp2)
	# Empirical distribution
	qW_0 = Empirical(params=w0)
	qW_1 = Empirical(params=w1)
	qW_2 = Empirical(params=w2)
	qb_0 = Empirical(params=b0)
	qb_1 = Empirical(params=b1)
	qb_2 = Empirical(params=b2)
	
	if str(sys.argv[3]) == 'hmc':	
		inference = ed.HMC({W_0: qW_0, b_0: qb_0, W_1: qW_1, b_1: qb_1,  W_2: qW_2, b_2: qb_2}, data={y: y_ph})
	if str(sys.argv[3]) == 'sghmc':	
		inference = ed.SGHMC({W_0: qW_0, b_0: qb_0, W_1: qW_1, b_1: qb_1,  W_2: qW_2, b_2: qb_2}, data={y: y_ph})

	# Initialse the inference variables
	if str(sys.argv[3]) == 'hmc':
		inference.initialize(step_size = leap_size, n_steps = step_no, n_print=100, 
			scale={y: float(mnist.train.num_examples) / N})
	if str(sys.argv[3]) == 'sghmc':
		inference.initialize(step_size = leap_size, friction=0.4, n_print=100, 
			scale={y: float(mnist.train.num_examples) / N})
	
	return ((x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, qW_0, qb_0, qW_1, qb_1, qW_2, qb_2, inference,
			p0, p1, p2, pp0, pp1, pp2, w0, w1, w2, b0, b1, b2)



# ============================================================================================
# Phase 1 of learning
# ============================================================================================

# Reset the tensorflow graph
tf.reset_default_graph()

# Build predictive graph
x_pred, ww0, ww1, ww2, bb0, bb1, bb2, y_pred = pred_graph()

# Build the initial graph inference graph
if str(sys.argv[4]) == 'laplace' or str(sys.argv[4]) == 'T':
	((x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, qW_0, qb_0, qW_1, qb_1, 
		qW_2, qb_2, inference, p0, p1, p2, pp0, pp1, pp2, w0, w1, w2, b0, b1, b2) = ed_graph_init()
else:
	((x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, 
		qW_0, qb_0, qW_1, qb_1, qW_2, qb_2, inference) = ed_graph_init()


with tf.Session() as sess:

	if str(sys.argv[4]) == 'laplace' or str(sys.argv[4]) == 'T':
		# Initialise all the vairables in the session.
		init = tf.global_variables_initializer()
		if str(sys.argv[4]) == 'laplace':
			sess.run(init, feed_dict={p0: np.random.laplace(size=[n_samp, D, n_hidden], scale=(std**2/D)),
				p1: np.random.laplace(size=[n_samp, n_hidden, n_hidden], scale=(std**2/n_hidden)),
				p2: np.random.laplace(size=[n_samp, n_hidden, K], scale=(std**2/n_hidden)), 
				pp0: np.random.laplace(size=[n_samp, n_hidden], scale=(std**2/D)),
				pp1: np.random.laplace(size=[n_samp, n_hidden], scale=(std**2/n_hidden)),
				pp2: np.random.laplace(size=[n_samp, K], scale=(std**2/n_hidden))})
		if str(sys.argv[4]) == 'T':
			sess.run(init, feed_dict={p0: np.random.standard_t(df, size=[n_samp, D, n_hidden]),
				p1: np.random.standard_t(df, size=[n_samp, n_hidden, n_hidden]), 
				p2: np.random.standard_t(df, size=[n_samp, n_hidden, K]), 
				pp0: np.random.standard_t(df, size=[n_samp, n_hidden]),
				pp1: np.random.standard_t(df, size=[n_samp, n_hidden]),
				pp2: np.random.standard_t(df, size=[n_samp, K])})

	if str(sys.argv[4]) == 'normal':
		tf.global_variables_initializer().run()

	if str(sys.argv[4]) != 'T':
		path =  ('../saved/' + str(n_hidden) +'units/2l_' + str(inference.n_iter*n_iter_learn) + 'rep/' + 
			str(sys.argv[3]) + '/' + str(sys.argv[4]))
	else:
		path =  ('../saved/' + str(n_hidden) +'units/2l_' + str(inference.n_iter*n_iter_learn) + 'rep/' + 
			str(sys.argv[3]) + '/' + 'T_' + str(df).replace('.','_'))

	if not os.path.exists(path):
	  os.makedirs(path)

	# Training - Phase 1
	test_acc = []

	for _ in range(inference.n_iter):
		# Start timer - make sure only the actual inference part is calculated
		if _ == 0:
			total = timeit.default_timer()
		start = timeit.default_timer()
		X_batch, Y_batch = mnist.train.next_batch(N)
		# TensorFlow method gives the label data in a one hot vetor format. We convert that into a single label.
		Y_batch = np.argmax(Y_batch,axis=1)
		info_dict = inference.update(feed_dict={x: resize(X_batch), y_ph: Y_batch})
		# info_dict = inference.update(feed_dict={x: X_batch, y_ph: Y_batch})
		inference.print_progress(info_dict)
		elapsed = timeit.default_timer() - start
		total = total + elapsed
		if (_ + 1 ) % 50 == 0 or _ == 0:
			y_post = ed.copy(y, {W_0: qW_0, W_1: qW_1, W_2: qW_2, b_0: qb_0, b_1: qb_1, b_2: qb_2})
			acc_tmp = ed.evaluate('sparse_categorical_accuracy', data={x: resize(X_test), y_post: Y_test}, n_samples=100)
			# acc_tmp = ed.evaluate('sparse_categorical_accuracy', data={x: X_test, y_post: Y_test})
			print('\nIter ', _+1, ' -- Accuracy: ', acc_tmp)
			test_acc.append(acc_tmp)		

	# Save test accuracy during training
	name = path + '/test_acc.csv'
	np.savetxt(name, test_acc, fmt = '%.5f', delimiter=',')

	## Model Evaluation
	#
	y_post = ed.copy(y, {W_0: qW_0, W_1: qW_1, W_2: qW_2, b_0: qb_0, b_1: qb_1, b_2: qb_2})

	W0_opt = (qW_0.params.eval()[nburn:, :, :]).mean(axis=0)
	W1_opt = (qW_1.params.eval()[nburn:, :, :]).mean(axis=0)
	W2_opt = (qW_2.params.eval()[nburn:, :, :]).mean(axis=0)
	b0_opt = (qb_0.params.eval()[nburn:, :]).mean(axis=0)
	b1_opt = (qb_1.params.eval()[nburn:, :]).mean(axis=0)
	b2_opt = (qb_2.params.eval()[nburn:, :]).mean(axis=0)

	y_post1 = ed.copy(y, {W_0: W0_opt, W_1: W1_opt, W_2: W2_opt, b_0: b0_opt, 
		b_1: b1_opt, b_2: b2_opt})

	mini_samp = 100

	print("Accuracy on test data:")
	acc1 = ed.evaluate('sparse_categorical_accuracy', data={x: resize(X_test), y_post: Y_test}, n_samples=100)
	# acc1 = ed.evaluate('sparse_categorical_accuracy', data={x: X_test, y_post: Y_test})
	print(acc1)


	print("Accuracy on test data: (using mean)")
	acc2 = ed.evaluate('sparse_categorical_accuracy', data={x: resize(X_test), y_post1: Y_test}, n_samples=100)
	print(acc2)

	pred_acc_list = np.zeros([mini_samp])
	preds = np.zeros([mini_samp, len(Y_test)])

	rnd = random.sample(range(nburn,n_samp), mini_samp)

	pW_0, pW_1, pW_2, pb_0, pb_1, pb_2 = (qW_0.params.eval()[rnd, :, :], 
		qW_1.params.eval()[rnd, :, :],
		qW_2.params.eval()[rnd, :, :],
		qb_0.params.eval()[rnd, :],
		qb_1.params.eval()[rnd, :],
		qb_2.params.eval()[rnd, :])

	for i in range(mini_samp):
		pred = sess.run(y_pred, feed_dict={x_pred: resize(X_test), ww0: pW_0[i, :, :], 
			bb0: pb_0[i, :], ww1: pW_1[i, :, :], bb1: pb_1[i, :], 
			ww2: pW_2[i, :, :], bb2: pb_2[i, :]})
		preds[i, :] = pred
		acc_tmp = mean_acc(Y_test, pred)
		pred_acc_list[i] = acc_tmp

	file_name = path + '/predictions_samples_not_burnin.npy'
	np.save(file_name, preds)
	file_name = path + '/pred_acc_samples_not_burnin.npy'
	np.save(file_name, pred_acc_list)

	mc_pred = sess.run(y_pred, feed_dict={x_pred: resize(X_test), ww0: pW_0.mean(axis=0),
		bb0: pb_0.mean(axis=0), ww1: pW_1.mean(axis=0), bb1: pb_1.mean(axis=0),
		ww2: pW_2.mean(axis=0), bb2: pb_2.mean(axis=0)})
	mc_acc = mean_acc(Y_test, mc_pred)
	print('MC accuracy -- ', mc_acc)

	del pW_0, pW_1, pW_2, pb_0, pb_1, pb_2

	# Trace plot
	#
	n_lags_used = n_samp - nburn
	acf_vals = np.zeros([18, n_lags_used])
	rnd0_i = random.sample(range(D), 2)
	rnd0_j = random.sample(range(n_hidden), 3)
	rnd1_i = random.sample(range(n_hidden), 2)
	rnd1_j = random.sample(range(n_hidden), 3)
	rnd2_j = random.sample(range(n_hidden), 3)
	rnd2_i = random.sample(range(K), 2)

	fig, ax = plt.subplots(6)
	for i in range(2):
		for j in range(3):	
			w_samp = qW_0.params.eval()[:, rnd0_i[i], rnd0_j[j]]
			acf_vals[i*3+j,:] = acf(w_samp[nburn:], nlags=n_lags_used)
			ax[i*3+j].plot(w_samp)
			ax[i*3+j].set_xlabel('Iteration')
	plt.subplots_adjust(hspace=0.05)
	plt.savefig(path + '/traceplot0_w0.png')
	plt.close(fig)


	fig, ax = plt.subplots(6)
	for i in range(2):
		for j in range(3):	
			w_samp = qW_1.params.eval()[:, rnd1_i[i], rnd1_j[j]]
			acf_vals[6+i*3+j, :] = acf(w_samp[nburn:], nlags=n_lags_used)
			ax[i*3+j].plot(w_samp)
			ax[i*3+j].set_xlabel('Iteration')
	plt.subplots_adjust(hspace=0.05)
	plt.savefig(path + '/traceplot0_w1.png')
	plt.close(fig)

	fig, ax = plt.subplots(6)
	for i in range(2):
		for j in range(3):	
			w_samp = qW_2.params.eval()[:, rnd2_j[j], rnd2_i[i]]
			acf_vals[12+i*3+j, :] = acf(w_samp[nburn:], nlags=n_lags_used)
			ax[i*3+j].plot(w_samp)
			ax[i*3+j].set_xlabel('Iteration')
	plt.subplots_adjust(hspace=0.05)
	plt.savefig(path + '/traceplot0_w2.png')
	plt.close(fig)

	# Auto-correlations to find the effective sample size
	#
	n_vec = np.zeros(18)

	for i in range(18):
		j = 0
		while acf_vals[i,j] > 0:
			n_vec[i] = j
			j = j + 1
	n_vec = n_vec.astype(np.int32)
	auto_corr_sum = 0

	for i in range(18):
		auto_corr_sum = auto_corr_sum + np.sum(acf_vals[i, 0:n_vec[i]])
	n_eff = int(1 + auto_corr_sum/9)

	print('N_eff = ', n_eff)

	W0_learnt = qW_0.sample(n_samp).eval()
	W1_learnt = qW_1.sample(n_samp).eval()
	W2_learnt = qW_2.sample(n_samp).eval()
	b0_learnt = qb_0.sample(n_samp).eval()
	b1_learnt = qb_1.sample(n_samp).eval()
	b2_learnt = qb_2.sample(n_samp).eval()

# =============================================================================================================
# Phase 2 of the training
# =============================================================================================================

inc_step = 1.0

for phase_iter in range(1, n_iter_learn):
	# Reset the tensorflow graph
	del x_pred, ww0, ww1, ww2, bb0, bb1, bb2, y_pred
	if phase_iter == 1 and str(sys.argv[4]) == 'normal':
		del (x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, qW_0, qb_0, qW_1, qb_1, qW_2, qb_2, inference
	else:
		del ((x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, qW_0, qb_0, qW_1, qb_1, 
			qW_2, qb_2, inference, p0, p1, p2, pp0, pp1, pp2, w0, w1, w2, b0, b1, b2)
	del X_batch, Y_batch
	del y_post, y_post1

	tf.reset_default_graph()

	# Build predictive graph
	x_pred, ww0, ww1, ww2, bb0, bb1, bb2, y_pred = pred_graph()

	# Increase the step size gradually for the first 2/3 of learning phases, then decrease for the last 1/3
	if phase_iter/n_iter_learn < 2/3:
		inc_step = 1.02*inc_step
	else:
		inc_step = 0.98*inc_step

	print('Iteration = ', str(phase_iter), ' -- Inc_step = ', str(inc_step))

	# Build the initial graph inference graph
	((x, y), y_ph, W_0, b_0, W_1, b_1, W_2, b_2, qW_0, qb_0, qW_1, qb_1, 
		qW_2, qb_2, inference, p0, p1, p2, pp0, pp1, pp2, w0, w1, w2, b0, b1, b2) = ed_graph_2(inc_step)

	# sess = ed.get_session()
	with tf.Session() as sess:

		# Initialise all the vairables in the session.
		init = tf.global_variables_initializer()

		sess.run(init, feed_dict={p0: W0_learnt, p1: W1_learnt, p2: W2_learnt, pp0: b0_learnt, pp1: b1_learnt, pp2: b2_learnt})

		del W0_learnt, W1_learnt, W2_learnt, b0_learnt, b1_learnt, b2_learnt

		# Training 
		test_acc = []

		for _ in range(inference.n_iter):
			start = timeit.default_timer()
			X_batch, Y_batch = mnist.train.next_batch(N)
			# TensorFlow method gives the label data in a one hot vetor format. We convert that into a single label.
			Y_batch = np.argmax(Y_batch,axis=1)
			info_dict = inference.update(feed_dict={x: resize(X_batch), y_ph: Y_batch})
			# info_dict = inference.update(feed_dict={x: X_batch, y_ph: Y_batch})
			inference.print_progress(info_dict)
			elapsed = timeit.default_timer() - start
			total = total + elapsed
			if (_ + 1 ) % 50 == 0 or _ == 0:
				y_post = ed.copy(y, {W_0: qW_0, W_1: qW_1, W_2: qW_2, b_0: qb_0, b_1: qb_1, b_2: qb_2})
				acc_tmp = ed.evaluate('sparse_categorical_accuracy', data={x: resize(X_test), y_post: Y_test}, n_samples=100)
				# acc_tmp = ed.evaluate('sparse_categorical_accuracy', data={x: X_test, y_post: Y_test})
				print('\nIter ', _+1, ' -- Accuracy: ', acc_tmp)
				test_acc.append(acc_tmp)		

		# Save test accuracy during training
		name = path + '/test_acc' + str(phase_iter) + '.csv'
		np.savetxt(name, test_acc, fmt = '%.5f', delimiter=',')

		## Model Evaluation
		#
		y_post = ed.copy(y, {W_0: qW_0, W_1: qW_1, W_2: qW_2, b_0: qb_0, b_1: qb_1, b_2: qb_2})

		W0_opt = (qW_0.params.eval()[nburn:, :, :]).mean(axis=0)
		W1_opt = (qW_1.params.eval()[nburn:, :, :]).mean(axis=0)
		W2_opt = (qW_2.params.eval()[nburn:, :, :]).mean(axis=0)
		b0_opt = (qb_0.params.eval()[nburn:, :]).mean(axis=0)
		b1_opt = (qb_1.params.eval()[nburn:, :]).mean(axis=0)
		b1_opt = (qb_2.params.eval()[nburn:, :]).mean(axis=0)

		y_post1 = ed.copy(y, {W_0: W0_opt, W_1: W1_opt, W_2: W2_opt, b_0: b0_opt, 
		b_1: b1_opt, b_2: b2_opt})

		mini_samp = 100

		print("Accuracy on test data:")
		acc1 = ed.evaluate('sparse_categorical_accuracy', data={x: resize(X_test), y_post: Y_test}, n_samples=100)
		print(acc1)


		print("Accuracy on test data: (using mean)")
		acc2 = ed.evaluate('sparse_categorical_accuracy', data={x: resize(X_test), y_post1: Y_test}, n_samples=100)
		print(acc2)

		pred_acc_list = np.zeros([mini_samp])
		preds = np.zeros([mini_samp, len(Y_test)])

		rnd = random.sample(range(nburn,n_samp), mini_samp)

		pW_0, pW_1, pW_2, pb_0, pb_1, pb_2 = (qW_0.params.eval()[rnd, :, :], 
			qW_1.params.eval()[rnd, :, :],
			qW_2.params.eval()[rnd, :, :],
			qb_0.params.eval()[rnd, :],
			qb_1.params.eval()[rnd, :],
			qb_2.params.eval()[rnd, :])

		for i in range(mini_samp):
			pred = sess.run(y_pred, feed_dict={x_pred: resize(X_test), ww0: pW_0[i, :, :], 
				bb0: pb_0[i, :], ww1: pW_1[i, :, :], bb1: pb_1[i, :], 
				ww2: pW_2[i, :, :], bb2: pb_2[i, :]})
			preds[i, :] = pred
			acc_tmp = mean_acc(Y_test, pred)
			pred_acc_list[i] = acc_tmp

			file_name = path + '/predictions_samples_not_burnin' + str(phase_iter) + '.npy'
			np.save(file_name, preds)
			file_name = path + '/pred_acc_samples_not_burnin' + str(phase_iter) + '.npy'
			np.save(file_name, pred_acc_list)


		mc_pred = sess.run(y_pred, feed_dict={x_pred: resize(X_test), ww0: pW_0.mean(axis=0), 
			bb0: pb_0.mean(axis=0), ww1: pW_1.mean(axis=0), bb1: pb_1.mean(axis=0), 
			ww2: pW_2.mean(axis=0), bb2: pb_2.mean(axis=0)})
		mc_acc = mean_acc(Y_test, mc_pred)
		print('MC accuracy -- ', mc_acc)

		del pW_0, pW_1, pW_2, pb_0, pb_1, pb_2

		# Trace plot
		#
		fig, ax = plt.subplots(6)
		for i in range(2):
			for j in range(3):	
				w_samp = qW_0.params.eval()[:, rnd0_i[i], rnd0_j[j]]
				acf_vals[i*3+j,:] = acf(w_samp[nburn:], nlags=n_lags_used)
				ax[i*3+j].plot(w_samp)
				ax[i*3+j].set_xlabel('Iteration')
		plt.subplots_adjust(hspace=0.05)
		plt.savefig(path + '/traceplot' + str(phase_iter) + '_w0.png')
		plt.close(fig)


		fig, ax = plt.subplots(6)
		for i in range(2):
			for j in range(3):	
				w_samp = qW_1.params.eval()[:, rnd1_i[i], rnd1_j[j]]
				acf_vals[6+i*3+j, :] = acf(w_samp[nburn:], nlags=n_lags_used)
				ax[i*3+j].plot(w_samp)
				ax[i*3+j].set_xlabel('Iteration')
		plt.subplots_adjust(hspace=0.05)
		plt.savefig(path + '/traceplot' + str(phase_iter) + '_w1.png')
		plt.close(fig)

		fig, ax = plt.subplots(6)
		for i in range(2):
			for j in range(3):	
				w_samp = qW_2.params.eval()[:, rnd2_j[j], rnd2_i[i]]
				acf_vals[12+i*3+j, :] = acf(w_samp[nburn:], nlags=n_lags_used)
				ax[i*3+j].plot(w_samp)
				ax[i*3+j].set_xlabel('Iteration')
		plt.subplots_adjust(hspace=0.05)
		plt.savefig(path + '/traceplot' + str(phase_iter) + '_w2.png')
		plt.close(fig)

		# Auto-correlations to find the effective sample size
		#
		n_vec = np.zeros(18)

		for i in range(18):
			j = 0
			while acf_vals[i,j] > 0:
				n_vec[i] = j
				j = j + 1
		n_vec = n_vec.astype(np.int32)
		auto_corr_sum = 0

		for i in range(18):
			auto_corr_sum = auto_corr_sum + np.sum(acf_vals[i, 0:n_vec[i]])
		n_eff = int(1 + auto_corr_sum/9)

		print('N_eff = ', n_eff)

		# Collected samples
		if phase_iter == 1:
			# Collected samples
			qW0_smp = qW_0.params.eval()[nburn:n_samp:n_eff, :, :]
			qW1_smp = qW_1.params.eval()[nburn:n_samp:n_eff, :, :]
			qW2_smp = qW_2.params.eval()[nburn:n_samp:n_eff, :, :]
			qb0_smp = qb_0.params.eval()[nburn:n_samp:n_eff, :]
			qb1_smp = qb_1.params.eval()[nburn:n_samp:n_eff, :]
			qb2_smp = qb_2.params.eval()[nburn:n_samp:n_eff, :]
			# Plot marginal distribution plots
			# (plotting only a sample of the plots)
			ii0 = random.sample(range(D), 4)
			jj0 = random.sample(range(n_hidden), 4)
			ii1 = random.sample(range(n_hidden), 4)
			jj1 = random.sample(range(K), 4)
		else:
			qW0_smp = np.concatenate([qW0_smp, qW_0.params.eval()[nburn:n_samp:n_eff, :, :]], 0)  
			qW1_smp = np.concatenate([qW1_smp, qW_1.params.eval()[nburn:n_samp:n_eff, :, :]], 0)  
			qW2_smp = np.concatenate([qW2_smp, qW_2.params.eval()[nburn:n_samp:n_eff, :, :]], 0)  
			qb0_smp = np.concatenate([qb0_smp, qb_0.params.eval()[nburn:n_samp:n_eff, :]], 0)  
			qb1_smp = np.concatenate([qb1_smp, qb_1.params.eval()[nburn:n_samp:n_eff, :]], 0)  
			qb2_smp = np.concatenate([qb2_smp, qb_2.params.eval()[nburn:n_samp:n_eff, :]], 0)  

		# Plot marginal distribution plots
		# (plotting only a sample of the plots)
		fig, ax = plt.subplots(3)
		for i in range(4):
			for j in range(4):
				sns.distplot(qW0_smp[:, ii0[i], jj0[j]], hist=False, rug=False, ax=ax[0])
				sns.distplot(qW1_smp[:, ii1[i], jj0[j]], hist=False, rug=False, ax=ax[1])
				sns.distplot(qW2_smp[:, ii1[i], jj1[j]], hist=False, rug=False, ax=ax[2])
		plt.subplots_adjust(hspace=0.2)
		plt.savefig(path + '/post_dist_' + str(phase_iter) + '.png')
		plt.close(fig)

		W0_learnt = qW_0.sample(n_samp).eval()
		W1_learnt = qW_1.sample(n_samp).eval()
		W2_learnt = qW_2.sample(n_samp).eval()
		b0_learnt = qb_0.sample(n_samp).eval()
		b1_learnt = qb_1.sample(n_samp).eval()
		b2_learnt = qb_2.sample(n_samp).eval()

# Save collected samples
#
np.save(path + '/qW0_samp.npy', qW0_smp)
np.save(path + '/qW1_samp.npy', qW1_smp)
np.save(path + '/qW2_samp.npy', qW2_smp)
np.save(path + '/qb0_samp.npy', qb0_smp)
np.save(path + '/qb1_samp.npy', qb1_smp)
np.save(path + '/qb2_samp.npy', qb2_smp)

print('Total number of samples collected -- ', np.shape(qW0_smp)[0])

# Final prediction
acc_final = []
conf_mat = np.zeros([np.shape(qW0_smp)[0], K, K])
probs = np.zeros([np.shape(Y_test)[0], K])

tf.reset_default_graph()
# Build predictive graph
x_pred, ww0, ww1, ww2, bb0, bb1, bb2, y_pred = pred_graph()
# Build predictive graph for class probabilities
x_in, w0_fin, b0_fin, w1_fin, b1_fin, w2_fin, b2_fin, prob_out = pred_graph_2()

with tf.Session() as sess:
	# Initialise all the vairables in the session.
	sess.run(tf.global_variables_initializer())

	for i in range(np.shape(qW0_smp)[0]):
		pred = sess.run(y_pred, feed_dict={x_pred: resize(X_test), ww0: qW0_smp[i, :, :],
				bb0: qb0_smp[i, :], ww1: qW1_smp[i, :, :], bb1: qb1_smp[i, :],
				ww2: qW2_smp[i, :, :], bb2: qb2_smp[i, :]})
		acc_final.append(mean_acc(Y_test, pred))
		conf_mat[i, :, :] = confusion_matrix(Y_test, pred)
		probs = probs + sess.run(prob_out, feed_dict={x_in: resize(X_test), w0_fin: qW0_smp[i, :, :],
				b0_fin: qb0_smp[i, :], w1_fin: qW1_smp[i, :, :], b1_fin: qb1_smp[i, :],
				w2_fin: qW2_smp[i, :, :], b2_fin: qb2_smp[i, :]})

	y_hat = np.reshape(np.argmax(probs, axis=1), [-1])
	fin_acc = mean_acc(Y_test, y_hat)
	print('Final prediction accuracy = ', fin_acc, ' +/- ', str(np.std(acc_final)))

	# Save info file
	print('Total time elapsed (seconds): ',total)
	info = ['Total algorithm time (seconds) -- ' + str(total), 'Batch size -- ' + str(N), 
	'Test accuracy (posterior) -- ' + str(acc1), 
	'Mean prediction accuracy (100 samples from posterior) -- ' + str(mc_acc),
	'Std of prediction accuracy (100 samples from posterior) -- ' + str(np.std(pred_acc_list)),
	'Final prediction accuracy -- ' + str(fin_acc) + ' +/- ' + str(np.std(acc_final)),
	'Effective Sample n -- ' + str(n_eff)]
	if str(sys.argv[3]) == 'hmc': 
		info.append('Test accuracy (100 sample MC estimate exluding burn-in) -- ' + str(acc2))
		info.append('Leapfrog step size -- ' + str(leap_size))
		info.append('Number of leapfrog steps -- ' + str(step_no))
		info.append('Burnin --' + str(nburn))
	if str(sys.argv[3]) == 'sghmc':
		info.append('Test accuracy (100 sample MC estimate exluding burn-in) -- ' + str(acc2))
		info.append('Leapfrog step size -- ' + str(leap_size))
		info.append('Burnin --' + str(nburn))
	name = path + '/info_file.csv'
	np.savetxt(name, info, fmt='%s' , delimiter=',')

	# Graph of drawn confussion matrices from the posterior
	conf_mat_mean = confusion_matrix(Y_test, y_hat)

	fig, ax = plt.subplots(1)
	cbar = ax.imshow((conf_mat_mean.T/np.sum(conf_mat_mean, axis=1)).T, cmap=plt.cm.gnuplot, interpolation='none')
	ax.set_xticks(np.arange(0, 9, 2))
	ax.grid(False)
	fig.colorbar(cbar, orientation='vertical')
	plt.savefig(path + '/predictive_conf_matrix.png')
	plt.close(fig)

	# Plot the standard deviation of the confussion matrix
	fig, ax = plt.subplots(1)
	cbar = ax.imshow(np.round(np.std(conf_mat,axis=0), decimals=4), cmap=plt.cm.gnuplot, interpolation='none')
	ax.set_xticks(np.arange(0, 9, 2))
	ax.grid(False)
	fig.colorbar(cbar, orientation='vertical')
	plt.subplots_adjust(hspace=0.2)
	plt.savefig(path + '/predictive_conf_matrix_std.png')
	plt.close(fig)